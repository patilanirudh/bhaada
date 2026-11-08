"""Owner A must never see or change owner B's data."""
from datetime import date

from tests.conftest import make_property, make_tenant


def test_owner_data_isolation(client, owner_a, owner_b):
    pa, ua = make_property(client, owner_a, name="A Towers")
    tb_prop, ub = make_property(client, owner_b, name="B Villa")
    ta = make_tenant(client, owner_a, ua["id"], date(2026, 1, 1), name="Tenant A")
    tb = make_tenant(client, owner_b, ub["id"], date(2026, 1, 1), name="Tenant B", phone="9876500000")

    # Lists only contain own rows
    props = client.get("/api/properties", headers=owner_a).json()
    assert [p["name"] for p in props] == ["A Towers"]
    tenants = client.get("/api/tenants", headers=owner_a).json()
    assert [t["full_name"] for t in tenants] == ["Tenant A"]
    entries = client.get("/api/rent/entries", headers=owner_a).json()
    assert entries and all(e["tenant_id"] == ta["id"] for e in entries)

    # Direct access to B's objects returns 404
    for url in (f"/api/properties/{tb_prop['id']}", f"/api/tenants/{tb['id']}", f"/api/tenants/{tb['id']}/ledger",
                f"/api/tenants/{tb['id']}/document-url", f"/api/reminders/whatsapp/tenant/{tb['id']}"):
        assert client.get(url, headers=owner_a).status_code == 404, url

    # Cannot modify B's data
    assert client.put(f"/api/properties/{tb_prop['id']}", json={"name": "Hacked"},
                      headers=owner_a).status_code == 404
    assert client.patch(f"/api/tenants/{tb['id']}", json={"full_name": "Hacked"}, headers=owner_a).status_code == 404
    assert client.post(f"/api/properties/{tb_prop['id']}/units", json={"name": "X"},
                       headers=owner_a).status_code == 404
    b_entry = client.get("/api/rent/entries", headers=owner_b).json()[0]
    r = client.post(f"/api/rent/entries/{b_entry['id']}/payments",
                    json={"amount": 100, "paid_on": "2026-01-02", "mode": "CASH"}, headers=owner_a)
    assert r.status_code == 404
    # Cannot attach own tenant to B's unit, nor create links for B's property
    assert client.patch(f"/api/tenants/{ta['id']}", json={"unit_id": ub["id"]}, headers=owner_a).status_code == 404
    assert client.post("/api/links", json={"property_id": tb_prop["id"]}, headers=owner_a).status_code == 404

    # Excel export only includes own tenants
    from io import BytesIO

    from openpyxl import load_workbook
    wb = load_workbook(BytesIO(client.get("/api/excel/export", headers=owner_a).content))
    names = [r[0] for r in wb["Tenants"].iter_rows(min_row=2, values_only=True)]
    assert names == ["Tenant A"]

    # B still intact
    assert client.get(f"/api/tenants/{tb['id']}", headers=owner_b).json()["full_name"] == "Tenant B"


def test_requires_auth(client):
    assert client.get("/api/tenants").status_code == 401
    assert client.get("/api/tenants", headers={"Authorization": "Bearer junk"}).status_code == 401
