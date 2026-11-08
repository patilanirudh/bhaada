from datetime import date

from app.db.models import ReminderLog, RentEntry, Tenant
from app.integrations import email as email_service
from app.utils.formatting import set_today_override
from tests.conftest import make_property, make_tenant

CRON = {"X-Cron-Secret": "test-cron-secret"}


def run(client, on: date):
    set_today_override(on)
    r = client.post(f"/api/jobs/run-daily?on={on.isoformat()}", headers=CRON)
    assert r.status_code == 200, r.text
    return r.json()


def test_cron_secret_required(client):
    assert client.post("/api/jobs/run-daily").status_code == 401
    assert client.post("/api/jobs/run-daily", headers={"X-Cron-Secret": "nope"}).status_code == 401


def test_daily_job_idempotent_and_reminder_schedule(client, owner_a, db):
    set_today_override(date(2026, 10, 1))
    _, u = make_property(client, owner_a)
    t = make_tenant(client, owner_a, u["id"], date(2026, 10, 1), due_day=5)
    email_service.OUTBOX.clear()

    # 3 days before the November due date: entry is created and DUE_SOON is sent once
    s1 = run(client, date(2026, 11, 2))
    assert db.query(RentEntry).filter_by(tenant_id=t["id"], month="2026-11").count() == 1
    sent_first = len(email_service.OUTBOX)
    assert s1["emails_sent"] >= 1 and sent_first >= 1
    assert any("upi://pay" in m.text or "Rent reminder" in m.subject for m in email_service.OUTBOX)

    # Running again the same day sends nothing new
    s2 = run(client, date(2026, 11, 2))
    assert s2["emails_sent"] == 0
    assert len(email_service.OUTBOX) == sent_first

    # Due today
    run(client, date(2026, 11, 5))
    assert db.query(ReminderLog).filter_by(tenant_id=t["id"], type="DUE_TODAY", status="SENT").count() == 1
    # Overdue every 3 days: day +3 and +6 only
    for d in (6, 7, 8, 8, 9, 10, 11):
        run(client, date(2026, 11, d))
    overdue = db.query(ReminderLog).filter_by(tenant_id=t["id"], type="OVERDUE", status="SENT", ref="2026-11").all()
    assert sorted(r.sent_on.day for r in overdue) == [8, 11]
    assert db.query(RentEntry).filter_by(tenant_id=t["id"], month="2026-11").one().status == "OVERDUE"


def test_failed_email_is_retried_next_run(client, owner_a, db):
    set_today_override(date(2026, 10, 1))
    _, u = make_property(client, owner_a)
    t = make_tenant(client, owner_a, u["id"], date(2026, 10, 1), due_day=5, email="fail@example.com")
    email_service.FAIL_ADDRESSES.add("fail@example.com")
    s = run(client, date(2026, 11, 2))
    assert s["emails_failed"] >= 1 and not s["errors"]
    email_service.FAIL_ADDRESSES.clear()
    s = run(client, date(2026, 11, 3))
    assert db.query(ReminderLog).filter_by(tenant_id=t["id"], type="DUE_SOON", status="SENT").count() == 1


def test_paid_entry_stops_reminders(client, owner_a, db):
    set_today_override(date(2026, 10, 1))
    _, u = make_property(client, owner_a)
    t = make_tenant(client, owner_a, u["id"], date(2026, 10, 1), due_day=5)
    run(client, date(2026, 11, 1))
    entry = db.query(RentEntry).filter_by(tenant_id=t["id"], month="2026-11").one()
    r = client.post(f"/api/rent/entries/{entry.id}/payments", headers=owner_a,
                    json={"amount": entry.amount_due, "paid_on": "2026-11-01", "mode": "UPI", "reference": "UTR1"})
    assert r.status_code == 201 and r.json()["status"] == "PAID"
    before = db.query(ReminderLog).filter_by(tenant_id=t["id"], ref="2026-11").filter(
        ReminderLog.type.in_(["DUE_SOON", "DUE_TODAY", "OVERDUE"])).count()
    for d in (3, 5, 8, 11):
        run(client, date(2026, 11, d))
    after = db.query(ReminderLog).filter_by(tenant_id=t["id"], ref="2026-11").filter(
        ReminderLog.type.in_(["DUE_SOON", "DUE_TODAY", "OVERDUE"])).count()
    assert after == before


def test_increment_notice_and_application(client, owner_a, db):
    set_today_override(date(2026, 1, 1))
    _, u = make_property(client, owner_a)
    t = make_tenant(client, owner_a, u["id"], date(2025, 12, 10), rent=10000, due_day=10)
    email_service.OUTBOX.clear()
    run(client, date(2026, 11, 15))  # 25 days before the anniversary
    notices = db.query(ReminderLog).filter_by(tenant_id=t["id"], type="INCREMENT_NOTICE", status="SENT").all()
    assert len(notices) == 1 and notices[0].ref == "2026-12-10"
    assert any("₹10,500" in m.text for m in email_service.OUTBOX)
    run(client, date(2026, 11, 16))
    assert db.query(ReminderLog).filter_by(tenant_id=t["id"], type="INCREMENT_NOTICE").count() == 1
    run(client, date(2026, 12, 10))
    db.expire_all()
    assert db.get(Tenant, t["id"]).current_rent == 10500
    dec = db.query(RentEntry).filter_by(tenant_id=t["id"], month="2026-12").one()
    assert dec.amount_due == 10500
    hist = client.get(f"/api/tenants/{t['id']}/rent-history", headers=owner_a).json()
    assert hist[0]["new_rent"] == 10500 and hist[0]["reason"] == "YEARLY_INCREMENT"


def test_agreement_expiry_notices(client, owner_a, db):
    set_today_override(date(2026, 10, 1))
    _, u = make_property(client, owner_a)
    t = make_tenant(client, owner_a, u["id"], date(2026, 1, 1), end=date(2026, 12, 31), due_day=28)
    run(client, date(2026, 11, 8))  # 53 days before: no notice yet
    assert db.query(ReminderLog).filter_by(tenant_id=t["id"], type="AGREEMENT_EXPIRY").count() == 0
    run(client, date(2026, 12, 1))
    run(client, date(2026, 12, 2))
    run(client, date(2026, 12, 24))
    refs = sorted(r.ref for r in db.query(ReminderLog).filter_by(tenant_id=t["id"], type="AGREEMENT_EXPIRY"))
    assert refs == ["30:2026-12-31", "7:2026-12-31"]
