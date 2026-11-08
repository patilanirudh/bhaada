from datetime import date
from io import BytesIO

from openpyxl import Workbook, load_workbook

from app.integrations import email as email_service
from app.integrations.storage import get_storage
from app.utils.formatting import set_today_override
from tests.conftest import make_property, make_tenant


def test_auth_flow(client):
    r = client.post("/api/auth/register", json={"name": "Suresh", "email": "s@example.com", "password": "password123"})
    assert r.status_code == 201
    assert "refresh_token" in r.cookies or "refresh_token" in client.cookies
    assert client.post("/api/auth/register", json={"name": "Xy", "email": "S@example.com",
                                                   "password": "password123"}).status_code == 409
    assert client.post("/api/auth/login", json={"email": "s@example.com", "password": "wrong"}).status_code == 401
    r = client.post("/api/auth/login", json={"email": "s@example.com", "password": "password123"})
    token = r.json()["access_token"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["name"] == "Suresh"
    assert client.post("/api/auth/refresh").status_code == 200
    client.post("/api/auth/logout")
    assert client.post("/api/auth/refresh").status_code == 401


def test_partial_and_full_payment_with_receipt(client, owner_a):
    set_today_override(date(2026, 11, 3))
    _, u = make_property(client, owner_a)
    t = make_tenant(client, owner_a, u["id"], date(2026, 11, 1), rent=15000, due_day=5)
    entry = client.get(f"/api/tenants/{t['id']}/ledger", headers=owner_a).json()[0]
    assert entry["month"] == "2026-11" and entry["amount_due"] == 15000
    email_service.OUTBOX.clear()
    r = client.post(f"/api/rent/entries/{entry['id']}/payments", headers=owner_a,
                    json={"amount": 5000, "paid_on": "2026-11-03", "mode": "CASH"})
    assert r.status_code == 201 and r.json()["status"] == "PARTIAL" and r.json()["amount_paid"] == 5000
    assert client.post(f"/api/rent/entries/{entry['id']}/payments", headers=owner_a,
                       json={"amount": 20000, "paid_on": "2026-11-03", "mode": "UPI"}).status_code == 400
    r = client.post(f"/api/rent/entries/{entry['id']}/payments", headers=owner_a,
                    json={"amount": 10000, "paid_on": "2026-11-03", "mode": "UPI", "reference": "UTR99"})
    assert r.json()["status"] == "PAID"
    pay = r.json()["payments"][-1]
    assert pay["has_receipt"] and pay["receipt_number"]
    url = client.get(f"/api/rent/payments/{pay['id']}/receipt-url", headers=owner_a).json()["url"]
    assert client.get(url).content.startswith(b"%PDF")
    mails = [m for m in email_service.OUTBOX if m.to == "ravi@example.com"]
    assert len(mails) == 2 and mails[0].attachments[0].data.startswith(b"%PDF")


def test_excel_export_autosave_and_import(client, owner_a, db):
    set_today_override(date(2026, 11, 3))
    _, u = make_property(client, owner_a)
    make_tenant(client, owner_a, u["id"], date(2026, 11, 1))
    r = client.get("/api/excel/export", headers=owner_a)
    wb = load_workbook(BytesIO(r.content))
    assert wb.sheetnames == ["Tenants", "Payments", "Rent History", "Summary"]
    ws = wb["Tenants"]
    assert ws.freeze_panes == "A2" and ws["A1"].font.bold
    assert ws["H2"].number_format.count("₹") >= 1
    # Auto-saved copy exists (written by background task)
    from app.db.models import Owner
    owner = db.query(Owner).filter_by(email="a@example.com").one()
    assert get_storage().read(f"owners/{owner.id}/rent-data.xlsx") is not None

    # Template download
    tpl = load_workbook(BytesIO(client.get("/api/excel/template", headers=owner_a).content))
    assert "Full Name" in [c.value for c in tpl["Tenants"][1]]

    # Import with custom headers
    wb2 = Workbook()
    ws2 = wb2.active
    ws2.append(["Name", "Mobile", "Building", "Flat", "Rent", "Joining Date", "Aadhaar"])
    ws2.append(["Asha Rao", "9123456780", "Blue Heights", "B-1", 12000, "01-Apr-2025", None])
    ws2.append(["Bad Row", "123", "Blue Heights", "B-2", "abc", "not a date", None])
    buf = BytesIO()
    wb2.save(buf)
    files = {"file": ("t.xlsx", buf.getvalue(), "application/octet-stream")}
    prev = client.post("/api/excel/import/preview", headers=owner_a, files=files).json()
    assert prev["mapping"]["full_name"] == "Name" and prev["mapping"]["unit"] == "Flat"
    assert prev["valid_count"] == 1 and prev["error_count"] == 1
    res = client.post("/api/excel/import/commit", headers=owner_a, files=files).json()
    assert res == {"imported": 1, "skipped": 1}
    names = [t["full_name"] for t in client.get("/api/tenants", headers=owner_a).json()]
    assert "Asha Rao" in names
    asha = next(t for t in client.get("/api/tenants", headers=owner_a).json() if t["full_name"] == "Asha Rao")
    assert asha["current_rent"] == 12000 and asha["status"] == "ACTIVE"


def test_vacate_settlement(client, owner_a):
    set_today_override(date(2026, 11, 10))
    _, u = make_property(client, owner_a)
    t = make_tenant(client, owner_a, u["id"], date(2026, 11, 1), rent=15000)
    body = {"vacate_date": "2026-11-30", "deductions": [{"label": "Painting", "amount": 2000}]}
    prev = client.post(f"/api/tenants/{t['id']}/settlement-preview", json=body, headers=owner_a).json()
    assert prev["deposit"] == 30000 and prev["pending_rent"] == 15000 and prev["refund"] == 13000
    r = client.post(f"/api/tenants/{t['id']}/vacate", json=body, headers=owner_a)
    assert r.status_code == 200 and r.json()["status"] == "VACATED" and r.json()["has_settlement_pdf"]
    url = client.get(f"/api/tenants/{t['id']}/settlement-url", headers=owner_a).json()["url"]
    assert client.get(url).content.startswith(b"%PDF")


def test_whatsapp_links_and_dashboard(client, owner_a):
    set_today_override(date(2026, 11, 7))
    client.put("/api/settings/profile", json={"upi_id": "suresh@okhdfc"}, headers=owner_a)
    _, u = make_property(client, owner_a)
    t = make_tenant(client, owner_a, u["id"], date(2026, 11, 1), rent=15750, due_day=5, name="Ravi Kumar")
    item = client.get(f"/api/reminders/whatsapp/tenant/{t['id']}", headers=owner_a).json()
    assert item["link"].startswith("https://wa.me/919876543210?text=")
    assert "%E2%82%B915%2C750" in item["link"]  # ₹15,750 url-encoded
    assert "suresh@okhdfc" in item["text"]
    q = client.get("/api/reminders/whatsapp/queue?kind=due", headers=owner_a).json()["items"]
    assert len(q) == 1 and q[0]["type"] == "OVERDUE"
    r = client.post("/api/reminders/whatsapp/log", headers=owner_a,
                    json={"tenant_id": t["id"], "type": "OVERDUE", "ref": "2026-11"})
    assert r.status_code == 201
    q = client.get("/api/reminders/whatsapp/queue?kind=due", headers=owner_a).json()["items"]
    assert q[0]["last_whatsapp_on"] == "2026-11-07"
    d = client.get("/api/dashboard", headers=owner_a).json()
    assert d["cards"]["expected"] == 15750 and d["cards"]["pending"] == 15750
    assert len(d["chart"]) == 12 and len(d["actions"]["overdue"]) == 1
