"""Demo data: one owner, two properties, five tenants (one pending) and some payments.

Run:  python -m app.scripts.seed          (after `alembic upgrade head`)
Login: demo@rentmanager.in / demo12345
"""
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.core.defaults import DEFAULT_HOUSE_RULES
from app.core.security import encrypt, hash_password
from app.db import session as database
from app.db.models import Owner, Payment, Property, RentEntry, Tenant, TenantStatus, Unit
from app.services.rent import compute_status, create_entry, ensure_entries, month_str, rent_on
from app.utils.formatting import today_ist
from app.utils.validators import verhoeff_check_digit

DEMO_EMAIL = "demo@rentmanager.in"

RULES = DEFAULT_HOUSE_RULES


def aadhaar(prefix: str) -> str:
    return prefix + verhoeff_check_digit(prefix)


def run() -> None:
    db = database.SessionLocal()
    if db.scalar(select(Owner).where(Owner.email == DEMO_EMAIL)):
        print("Demo data already present. Login: demo@rentmanager.in / demo12345")
        return
    today = today_ist()
    owner = Owner(name="Suresh Sharma", email=DEMO_EMAIL, password_hash=hash_password("demo12345"),
                  phone="+919812345678", upi_id="suresh@okhdfc", preferred_language="en")
    db.add(owner)
    db.flush()

    p1 = Property(owner_id=owner.id, name="Green Residency", address="Plot 12, Baner Road, Pune 411045",
                  house_rules=RULES)
    p2 = Property(owner_id=owner.id, name="Lakeview Apartments", address="Sector 21, Kharghar, Navi Mumbai",
                  house_rules=RULES)
    db.add_all([p1, p2])
    db.flush()
    units = {}
    for prop, names, rent in ((p1, ["Flat 101", "Flat 203", "Flat 304"], 15000), (p2, ["A-12", "B-07"], 18000)):
        for n in names:
            u = Unit(owner_id=owner.id, property_id=prop.id, name=n, default_rent=rent)
            db.add(u)
            db.flush()
            units[n] = u

    def tenant(name, phone, email, unit, start, rent, due_day, id_type, id_num, end=None,
               status=TenantStatus.ACTIVE):
        u = units[unit]
        t = Tenant(owner_id=owner.id, property_id=u.property_id, unit_id=u.id, full_name=name, phone=phone,
                   email=email, permanent_address="Pune, Maharashtra", id_type=id_type,
                   id_number_encrypted=encrypt(id_num), id_last4=id_num[-4:], security_deposit=rent * 2,
                   agreement_start_date=start, agreement_end_date=end, base_rent=rent, rent_base_date=start,
                   increment_percent=5.0, due_day=due_day, status=status,
                   consent_given_at=datetime.now(UTC))
        t.current_rent = rent_on(t, today)
        db.add(t)
        db.flush()
        return t

    m3 = (today.replace(day=1) - timedelta(days=80)).replace(day=1)  # ~3 months ago
    t1 = tenant("Ravi Kumar", "+919876543210", "ravi.demo@example.com", "Flat 203",
                date(today.year - 1, today.month, 1) if today.month != 2 else date(today.year - 1, 2, 1),
                15000, 5, "AADHAAR", aadhaar("23456789012"), end=today + timedelta(days=25))
    t2 = tenant("Priya Nair", "+919845012345", "priya.demo@example.com", "Flat 101", m3, 14000, 5, "PAN",
                "ABCPN1234K")
    t3 = tenant("Mohammed Irfan", "+919900112233", "irfan.demo@example.com", "A-12",
                (today - timedelta(days=340)), 18000, 10, "AADHAAR", aadhaar("34567890123"))
    t4 = tenant("Anita Desai", "+919822334455", None, "B-07", m3, 17500, 1, "PAN", "AKDPD5678L")
    tenant("Vikram Singh", "+919811223344", "vikram.demo@example.com", "Flat 304", today, 0, 5, "AADHAAR",
           aadhaar("45678901234"), status=TenantStatus.PENDING_APPROVAL)

    # Ledger: entries from each start month up to now
    for t in (t1, t2, t3, t4):
        start_m = max(month_str(t.agreement_start_date), month_str(m3))
        create_entry(db, t, start_m, today)
        ensure_entries(db, t, today)

    # Payments: all past months paid except a couple, so the dashboard has overdue/partial items
    n = 0
    for e in db.scalars(select(RentEntry).where(RentEntry.owner_id == owner.id).order_by(RentEntry.due_date)):
        if e.due_date >= today.replace(day=1):
            continue  # current month left unpaid
        if e.tenant_id == t4.id and e.month == month_str(today.replace(day=1) - timedelta(days=1)):
            amount = e.amount_due // 2  # partial
        else:
            amount = e.amount_due
        n += 1
        db.add(Payment(owner_id=owner.id, rent_entry_id=e.id, amount=amount, paid_on=e.due_date,
                       mode="UPI" if n % 2 else "CASH", reference=f"UTR{100000 + n}" if n % 2 else None,
                       receipt_number=f"RM{owner.id}-{e.due_date:%y%m}-{n:05d}"))
        e.amount_paid = amount
        e.status = compute_status(e, today)
    db.commit()
    print("Demo data created. Login: demo@rentmanager.in / demo12345")
    db.close()


if __name__ == "__main__":
    run()
