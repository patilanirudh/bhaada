"""Regression tests for issues found on the live deployment (Render free plan + Supabase)."""
import base64
from datetime import date

import httpx
import pytest

from app.core.config import Settings, get_settings
from app.integrations import email as email_mod
from app.integrations import storage as storage_mod
from app.integrations.storage import LocalStorage, StorageError, SupabaseStorage, set_storage
from app.utils.formatting import set_today_override
from tests.conftest import make_property, make_tenant


# ---------- settings: pasted secrets with stray whitespace / newlines ----------
def test_settings_strip_trailing_newlines(monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "sb_secret_abc\n")
    monkeypatch.setenv("SUPABASE_URL", "  https://x.supabase.co \n")
    s = Settings()
    assert s.supabase_service_key == "sb_secret_abc"
    assert s.supabase_url == "https://x.supabase.co"


def test_production_guard_requires_brevo_key():
    s = Settings(environment="production", jwt_secret="x" * 40, fernet_key="k", cron_secret="y" * 20,
                 cookie_secure=True, frontend_url="https://a.b", database_url="postgresql://u:p@h/d",
                 storage_backend="supabase", email_backend="brevo", brevo_api_key="")
    with pytest.raises(RuntimeError, match="BREVO_API_KEY"):
        s.validate_for_production()


# ---------- storage: clear errors instead of anonymous crashes ----------
def _fake_request(status: int, body: dict | None = None, exc: Exception | None = None):
    def fake(method, url, **kw):
        if exc:
            raise exc
        return httpx.Response(status, json=body or {}, request=httpx.Request(method, url))
    return fake


def test_supabase_errors_are_clear(monkeypatch):
    s = SupabaseStorage("https://x.supabase.co", "sb_secret_abc", "rent-private")
    monkeypatch.setattr(storage_mod.httpx, "request", _fake_request(403, {"message": "signature verification failed"}))
    with pytest.raises(StorageError, match=r"upload failed \(403\): signature verification failed"):
        s.save("a/b.pdf", b"x", "application/pdf")
    # malformed header value (e.g. key with an embedded newline) -> StorageError, not a crash
    monkeypatch.setattr(storage_mod.httpx, "request", _fake_request(0, exc=ValueError("Invalid header value")))
    with pytest.raises(StorageError, match="signed link failed: ValueError"):
        s.signed_url("a/b.pdf")
    # missing object -> None; delete never raises
    monkeypatch.setattr(storage_mod.httpx, "request", _fake_request(400, {"error": "not_found"}))
    assert s.read("missing.xlsx") is None
    s.delete("missing.xlsx")


def test_supabase_not_configured():
    with pytest.raises(StorageError, match="not configured"):
        SupabaseStorage("", "", "rent-private")


class _BrokenStorage(LocalStorage):
    def save(self, path, data, content_type):
        raise StorageError("Supabase upload failed (401): Invalid API key")

    def signed_url(self, path, seconds=None):
        raise StorageError("Supabase signed link failed (401): Invalid API key")


@pytest.fixture()
def broken_storage(tmp_path):
    set_storage(_BrokenStorage(str(tmp_path)))
    yield
    set_storage(None)


def test_payment_saved_even_if_receipt_upload_fails(client, owner_a, broken_storage):
    """The reported bug: 'Mark as paid' returned 500 when storage was misconfigured."""
    set_today_override(date(2026, 11, 8))
    _, u = make_property(client, owner_a)
    t = make_tenant(client, owner_a, u["id"], date(2026, 11, 8), rent=10000)
    entry = client.get(f"/api/tenants/{t['id']}/ledger", headers=owner_a).json()[0]
    email_mod.OUTBOX.clear()
    r = client.post(f"/api/rent/entries/{entry['id']}/payments", headers=owner_a,
                    json={"amount": 10000, "paid_on": "2026-11-08", "mode": "CASH"})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "PAID"
    assert r.json()["payments"][0]["has_receipt"] is False
    # the PDF receipt is still emailed to the tenant
    sent = [m for m in email_mod.OUTBOX if m.to == "ravi@example.com"]
    assert sent and sent[0].attachments[0].data.startswith(b"%PDF")


def test_storage_error_returns_friendly_503(client, owner_a, broken_storage):
    set_today_override(date(2026, 11, 8))
    r = client.get("/api/excel/latest", headers=owner_a)
    assert r.status_code == 503
    assert "File storage is not available" in r.json()["detail"]
    assert "Invalid API key" not in r.json()["detail"]  # internals stay in server logs


# ---------- email over HTTPS (Brevo) where SMTP ports are blocked ----------
@pytest.fixture()
def brevo(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "email_backend", "brevo")
    monkeypatch.setattr(s, "brevo_api_key", "xkeysib-test")
    monkeypatch.setattr(s, "email_sender_address", "rent@example.com")
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers})
        return httpx.Response(201, json={"messageId": "<1@x>"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(email_mod.httpx, "post", fake_post)
    return calls


def test_brevo_payload(brevo):
    creds = email_mod.SmtpCredentials("ignored@gmail.com", "", "Suresh Sharma")
    email_mod.send_email(creds, "t@example.com", "Rent receipt", "Thanks!", None,
                         [email_mod.Attachment("r.pdf", b"%PDF-1")], reply_to="owner@example.com")
    c = brevo[0]
    assert c["url"] == "https://api.brevo.com/v3/smtp/email"
    assert c["headers"]["api-key"] == "xkeysib-test"
    j = c["json"]
    assert j["sender"] == {"email": "rent@example.com", "name": "Suresh Sharma"}
    assert j["to"] == [{"email": "t@example.com"}] and j["replyTo"] == {"email": "owner@example.com"}
    assert j["textContent"] == "Thanks!" and "Thanks!" in j["htmlContent"]
    assert base64.b64decode(j["attachment"][0]["content"]) == b"%PDF-1"


def test_brevo_error_is_email_error(monkeypatch, brevo):
    monkeypatch.setattr(email_mod.httpx, "post", lambda *a, **k: httpx.Response(
        400, json={"code": "unauthorized", "message": "Sender not verified"}, request=httpx.Request("POST", "u")))
    with pytest.raises(email_mod.EmailError, match="Sender not verified"):
        email_mod.send_email(None, "t@example.com", "s", "b")


def test_service_email_mode_in_api(client, owner_a, brevo):
    assert client.get("/api/auth/me", headers=owner_a).json()["email_mode"] == "service"
    assert client.get("/api/dashboard/actions", headers=owner_a).json()["email_ready"] is True
    r = client.post("/api/settings/gmail/test", headers=owner_a)  # works without owner Gmail
    assert r.status_code == 200 and brevo[-1]["json"]["to"] == [{"email": "a@example.com"}]
