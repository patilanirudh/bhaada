from datetime import date

from app.models import RentHistory, Tenant, TenantStatus
from app.services.rent import (
    add_years,
    apply_increment,
    calculate_rent,
    completed_years,
    due_date_for,
    next_anniversary,
    rebase_rent,
    rent_on,
)


def test_completed_years():
    s = date(2024, 4, 1)
    assert completed_years(s, date(2024, 4, 1)) == 0
    assert completed_years(s, date(2025, 3, 31)) == 0
    assert completed_years(s, date(2025, 4, 1)) == 1
    assert completed_years(s, date(2027, 4, 2)) == 3
    assert completed_years(s, date(2023, 1, 1)) == 0


def test_leap_day_anniversary():
    s = date(2024, 2, 29)
    assert add_years(s, 1) == date(2025, 2, 28)
    assert completed_years(s, date(2025, 2, 28)) == 1
    assert completed_years(s, date(2025, 2, 27)) == 0


def test_calculate_rent_formula():
    s = date(2023, 1, 10)
    assert calculate_rent(15000, 5, s, date(2023, 6, 1)) == 15000
    assert calculate_rent(15000, 5, s, date(2024, 1, 10)) == 15750
    assert calculate_rent(15000, 5, s, date(2025, 1, 10)) == 16538  # 16537.5 rounds half up
    assert calculate_rent(15000, 5, s, date(2026, 1, 10)) == 17364  # 17364.375
    assert calculate_rent(10000, 0, s, date(2030, 1, 1)) == 10000
    assert calculate_rent(10000, 7.5, s, date(2024, 1, 10)) == 10750


def test_next_anniversary():
    s = date(2025, 11, 20)
    assert next_anniversary(s, date(2025, 11, 20)) == date(2026, 11, 20)
    assert next_anniversary(s, date(2026, 11, 19)) == date(2026, 11, 20)
    assert next_anniversary(s, date(2026, 11, 20)) == date(2027, 11, 20)


def _tenant(db, owner_id, **kw):
    t = Tenant(owner_id=owner_id, full_name="T", phone="+919876543210", status=TenantStatus.ACTIVE, **kw)
    db.add(t)
    db.flush()
    return t


def test_increment_applies_once_on_anniversary(client, owner_a, db):
    from app.models import Owner
    owner = db.query(Owner).first()
    t = _tenant(db, owner.id, base_rent=10000, current_rent=10000, increment_percent=10,
                agreement_start_date=date(2025, 6, 15), rent_base_date=date(2025, 6, 15), due_day=5)
    assert apply_increment(db, t, date(2026, 6, 14)) is None
    h = apply_increment(db, t, date(2026, 6, 15))
    assert h is not None and h.old_rent == 10000 and h.new_rent == 11000 and h.effective_from == date(2026, 6, 15)
    assert t.current_rent == 11000
    assert apply_increment(db, t, date(2026, 6, 16)) is None  # idempotent
    assert db.query(RentHistory).filter_by(tenant_id=t.id).count() == 1
    h2 = apply_increment(db, t, date(2027, 6, 15))
    assert h2.new_rent == 12100


def test_manual_change_rebases_formula(client, owner_a, db):
    from app.models import Owner
    owner = db.query(Owner).first()
    t = _tenant(db, owner.id, base_rent=10000, current_rent=10500, increment_percent=5,
                agreement_start_date=date(2024, 3, 1), rent_base_date=date(2024, 3, 1), due_day=5)
    rebase_rent(t, 12000, date(2025, 8, 1))
    assert t.rent_base_date == date(2025, 3, 1)
    assert rent_on(t, date(2026, 2, 28)) == 12000
    assert rent_on(t, date(2026, 3, 1)) == 12600


def test_due_date_first_month_not_before_start():
    t = Tenant(due_day=5, agreement_start_date=date(2026, 11, 20))
    assert due_date_for(t, "2026-11") == date(2026, 11, 20)
    assert due_date_for(t, "2026-12") == date(2026, 12, 5)
