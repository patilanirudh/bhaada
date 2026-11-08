"""Security & privacy behaviour: erasure, production config guard, rate limits, error hygiene."""
from datetime import date

import pytest

from app.core.config import Settings
from app.utils.formatting import set_today_override
from tests.conftest import make_property, make_tenant


def test_erase_personal_data_keeps_financial_records(client, owner_a):
    set_today_override(date(2026, 11, 10))
    _, u = make_property(client, owner_a)
    t = make_tenant(client, owner_a, u["id"], date(2026, 11, 1))
    # Cannot erase an active tenant
    assert client.post(f"/api/tenants/{t['id']}/erase", headers=owner_a).status_code == 400
    client.post(f"/api/tenants/{t['id']}/vacate", json={"vacate_date": "2026-11-30"}, headers=owner_a)
    r = client.post(f"/api/tenants/{t['id']}/erase", headers=owner_a)
    assert r.status_code == 200
    out = r.json()
    assert out["full_name"].startswith("Erased tenant") and out["email"] is None and out["phone"] == ""
    assert out["id_masked"] == "—" and not out["has_settlement_pdf"]
    # Ledger rows (financial records) survive
    assert client.get(f"/api/tenants/{t['id']}/ledger", headers=owner_a).json()


def test_production_config_guard():
    unsafe = Settings(environment="production", jwt_secret="change-me", fernet_key="", cron_secret="dev",
                      cookie_secure=False, frontend_url="http://x", database_url="sqlite://",
                      storage_backend="local", email_backend="console")
    with pytest.raises(RuntimeError) as e:
        unsafe.validate_for_production()
    for word in ("JWT_SECRET", "FERNET_KEY", "CRON_SECRET", "COOKIE_SECURE", "FRONTEND_URL", "DATABASE_URL",
                 "STORAGE_BACKEND", "EMAIL_BACKEND"):
        assert word in str(e.value)
    safe = Settings(environment="production", jwt_secret="x" * 40, fernet_key="k", cron_secret="y" * 20,
                    cookie_secure=True, frontend_url="https://app.example.com",
                    database_url="postgresql://u:p@h/db", storage_backend="supabase", email_backend="smtp")
    safe.validate_for_production()  # no error


def test_per_account_login_limit(client):
    client.post("/api/auth/register", json={"name": "Victim", "email": "v@example.com", "password": "password123"})
    codes = [client.post("/api/auth/login", json={"email": "v@example.com", "password": "wrong"},
                         headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code for i in range(12)]
    assert codes[:10] == [401] * 10 and 429 in codes[10:]


def test_error_responses_and_headers(client, owner_a):
    r = client.get("/api/tenants/999999", headers=owner_a)
    assert r.status_code == 404 and r.json()["detail"] == "Tenant not found"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Request-ID"]
