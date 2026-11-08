from datetime import datetime, timedelta, timezone

from app.models import RegistrationLink, Tenant
from app.security import decrypt
from app.services import email as email_service
from tests.conftest import PDF, PNG, make_property, valid_aadhaar


def _form(**over):
    data = {"full_name": "Ravi Kumar", "phone": "9876543210", "email": "ravi@example.com",
            "permanent_address": "12 MG Road, Pune", "id_type": "AADHAAR", "id_number": valid_aadhaar(),
            "consent": "true", "rules_accepted": "true", "website": ""}
    data.update(over)
    return data


def _files(content=PDF, name="aadhaar.pdf"):
    return {"id_document": (name, content, "application/pdf")}


def _link(client, headers, **kw):
    p, u = make_property(client, headers)
    r = client.post("/api/links", json={"property_id": p["id"], "unit_id": u["id"], **kw}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_full_registration_and_approval(client, owner_a, db):
    link = _link(client, owner_a)
    assert len(link["token"]) >= 32
    assert link["url"].endswith(f"/register/{link['token']}")
    assert link["whatsapp_url"].startswith("https://wa.me/?text=")

    info = client.get(f"/api/public/register/{link['token']}")
    assert info.status_code == 200 and info.json()["property_name"] == "Green Residency"
    assert "No smoking" in info.json()["house_rules"]

    r = client.post(f"/api/public/register/{link['token']}", data=_form(), files=_files())
    assert r.status_code == 201, r.text
    t = db.query(Tenant).one()
    assert t.status == "PENDING_APPROVAL" and t.consent_given_at is not None
    assert t.id_last4 == valid_aadhaar()[-4:]
    assert t.id_number_encrypted != valid_aadhaar() and decrypt(t.id_number_encrypted) == valid_aadhaar()
    assert t.phone == "+919876543210"
    db.refresh(db.get(RegistrationLink, link["id"]))
    assert db.get(RegistrationLink, link["id"]).use_count == 1
    # Owner notified, without the ID number
    assert any("New tenant registration" in m.subject for m in email_service.OUTBOX)
    assert all(valid_aadhaar() not in m.text for m in email_service.OUTBOX)

    # UI only sees masked ID
    out = client.get(f"/api/tenants/{t.id}", headers=owner_a).json()
    assert out["id_masked"] == f"XXXX-XXXX-{valid_aadhaar()[-4:]}"
    assert valid_aadhaar() not in str(out)

    # Signed document URL works, then fails with a bad token
    url = client.get(f"/api/tenants/{t.id}/document-url", headers=owner_a).json()["url"]
    assert client.get(url).content == PDF
    assert client.get("/api/files/signed?token=bad").status_code == 403

    r = client.post(f"/api/tenants/{t.id}/approve", headers=owner_a, json={
        "base_rent": 15000, "security_deposit": 30000, "agreement_start_date": "2026-11-01", "due_day": 5,
        "increment_percent": 5})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ACTIVE"
    welcome = [m for m in email_service.OUTBOX if m.to == "ravi@example.com"]
    assert welcome and "No smoking" in welcome[0].text
    assert client.get(f"/api/tenants/{t.id}/ledger", headers=owner_a).json()  # first rent entry exists


def test_link_max_uses(client, owner_a):
    link = _link(client, owner_a, max_uses=1)
    assert client.post(f"/api/public/register/{link['token']}", data=_form(), files=_files()).status_code == 201
    r = client.post(f"/api/public/register/{link['token']}", data=_form(), files=_files())
    assert r.status_code == 410
    assert client.get(f"/api/public/register/{link['token']}").status_code == 410


def test_link_expiry(client, owner_a, db):
    link = _link(client, owner_a)
    row = db.get(RegistrationLink, link["id"])
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    r = client.get(f"/api/public/register/{link['token']}")
    assert r.status_code == 410 and "expired" in r.json()["detail"]
    assert client.post(f"/api/public/register/{link['token']}", data=_form(), files=_files()).status_code == 410


def test_link_deactivated_and_unknown(client, owner_a):
    link = _link(client, owner_a)
    client.post(f"/api/links/{link['id']}/deactivate", headers=owner_a)
    assert client.get(f"/api/public/register/{link['token']}").status_code == 410
    assert client.get("/api/public/register/doesnotexist").status_code == 404


def test_validation_errors(client, owner_a, db):
    link = _link(client, owner_a, max_uses=10)
    tok = link["token"]
    bad_aadhaar = valid_aadhaar()[:-1] + str((int(valid_aadhaar()[-1]) + 1) % 10)
    assert client.post(f"/api/public/register/{tok}", data=_form(id_number=bad_aadhaar), files=_files()).status_code == 422
    assert client.post(f"/api/public/register/{tok}", data=_form(id_type="PAN", id_number="ABC12"),
                       files=_files()).status_code == 422
    assert client.post(f"/api/public/register/{tok}", data=_form(consent="false"), files=_files()).status_code == 422
    assert client.post(f"/api/public/register/{tok}", data=_form(rules_accepted="false"),
                       files=_files()).status_code == 422
    # Fake PDF (wrong magic bytes) is rejected even with .pdf extension
    r = client.post(f"/api/public/register/{tok}", data=_form(), files=_files(b"MZ\x90 not a pdf", "x.pdf"))
    assert r.status_code == 400
    # Too large
    big = PNG + b"0" * (5 * 1024 * 1024)
    assert client.post(f"/api/public/register/{tok}", data=_form(), files=_files(big, "big.png")).status_code == 400
    # Missing document
    assert client.post(f"/api/public/register/{tok}", data=_form()).status_code == 422
    # PAN path works
    r = client.post(f"/api/public/register/{tok}", data=_form(id_type="PAN", id_number="abcde1234f"),
                    files=_files(PNG, "pan.png"))
    assert r.status_code == 201, r.text
    assert db.query(Tenant).one().id_last4 == "234F"


def test_honeypot_and_rate_limit(client, owner_a, db):
    link = _link(client, owner_a, max_uses=50)
    tok = link["token"]
    r = client.post(f"/api/public/register/{tok}", data=_form(website="http://spam"), files=_files())
    assert r.status_code == 201 and db.query(Tenant).count() == 0  # looks like success to bots
    codes = [client.post(f"/api/public/register/{tok}", data=_form(consent="false"), files=_files()).status_code
             for _ in range(12)]
    assert 429 in codes


def test_reject_deletes_documents(client, owner_a, db):
    link = _link(client, owner_a)
    client.post(f"/api/public/register/{link['token']}", data=_form(), files=_files())
    t = db.query(Tenant).one()
    r = client.post(f"/api/tenants/{t.id}/reject", headers=owner_a)
    assert r.json()["status"] == "REJECTED" and r.json()["has_id_document"] is False
