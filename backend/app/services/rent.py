"""Rent calculation, ledger generation and status rules."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import RentEntry, RentHistory, RentStatus, Tenant, TenantStatus

ENTRY_HORIZON_DAYS = 7  # create next month's entry this many days before its due date


# ---------- date helpers ----------
def add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 Feb in a non-leap year
        return d.replace(year=d.year + years, day=28)


def completed_years(start: date, on: date) -> int:
    if on < start:
        return 0
    years = on.year - start.year
    if add_years(start, years) > on:
        years -= 1
    return max(0, years)


def latest_anniversary(start: date, on: date) -> date:
    return add_years(start, completed_years(start, on))


def next_anniversary(start: date, after: date) -> date:
    """First anniversary (year >= 1) strictly after ``after``."""
    n = max(1, completed_years(start, after) + 1)
    return add_years(start, n)


def month_str(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def next_month(month: str) -> str:
    y, m = map(int, month.split("-"))
    return f"{y + (m == 12):04d}-{(m % 12) + 1:02d}"


def month_start(month: str) -> date:
    y, m = map(int, month.split("-"))
    return date(y, m, 1)


# ---------- rent formula ----------
def round_rupee(value: float | Decimal) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calculate_rent(base_rent: int, increment_percent: float, start: date, on: date) -> int:
    """current = base × (1 + pct/100) ^ completed_years, rounded to the nearest rupee."""
    years = completed_years(start, on)
    factor = (Decimal(1) + Decimal(str(increment_percent)) / Decimal(100)) ** years
    return round_rupee(Decimal(base_rent) * factor)


def rent_on(tenant: Tenant, on: date) -> int:
    anchor = tenant.rent_base_date or tenant.agreement_start_date
    if not anchor:
        return tenant.base_rent
    return calculate_rent(tenant.base_rent, tenant.increment_percent, anchor, on)


def rebase_rent(tenant: Tenant, new_base: int, today: date) -> None:
    """Restart the formula from ``new_base`` at the latest anniversary (manual rent / % change)."""
    tenant.base_rent = new_base
    if tenant.agreement_start_date:
        tenant.rent_base_date = latest_anniversary(tenant.agreement_start_date, today)
    tenant.current_rent = new_base


# ---------- ledger ----------
def due_date_for(tenant: Tenant, month: str) -> date:
    d = month_start(month).replace(day=tenant.due_day)
    if tenant.agreement_start_date and month == month_str(tenant.agreement_start_date):
        d = max(d, tenant.agreement_start_date)
    return d


def compute_status(entry: RentEntry, today: date) -> str:
    if entry.amount_paid >= entry.amount_due:
        return RentStatus.PAID
    if entry.due_date < today:
        return RentStatus.OVERDUE
    if entry.amount_paid > 0:
        return RentStatus.PARTIAL
    return RentStatus.DUE


def create_entry(db: Session, tenant: Tenant, month: str, today: date) -> RentEntry:
    existing = db.scalar(select(RentEntry).where(RentEntry.tenant_id == tenant.id, RentEntry.month == month))
    if existing:
        return existing
    due = due_date_for(tenant, month)
    entry = RentEntry(owner_id=tenant.owner_id, tenant_id=tenant.id, month=month,
                      amount_due=rent_on(tenant, due), amount_paid=0, due_date=due)
    entry.status = compute_status(entry, today)
    db.add(entry)
    db.flush()
    return entry


def first_month(tenant: Tenant, today: date) -> str:
    start = tenant.agreement_start_date or today
    return max(month_str(start), month_str(today))


def ensure_entries(db: Session, tenant: Tenant, today: date, horizon_days: int = ENTRY_HORIZON_DAYS) -> list[RentEntry]:
    """Create missing monthly entries up to the month whose due date falls within the horizon."""
    if tenant.status != TenantStatus.ACTIVE:
        return []
    created: list[RentEntry] = []
    last = db.scalar(select(func.max(RentEntry.month)).where(RentEntry.tenant_id == tenant.id))
    month = next_month(last) if last else first_month(tenant, today)
    limit = today + timedelta(days=horizon_days)
    for _ in range(36):  # safety bound
        if due_date_for(tenant, month) > limit:
            break
        created.append(create_entry(db, tenant, month, today))
        month = next_month(month)
    return created


def refresh_statuses(db: Session, today: date, owner_id: int | None = None) -> int:
    """Mark unpaid entries past their due date as OVERDUE. Returns number changed."""
    stmt = select(RentEntry).where(RentEntry.status.in_([RentStatus.DUE, RentStatus.PARTIAL]),
                                   RentEntry.due_date < today)
    if owner_id is not None:
        stmt = stmt.where(RentEntry.owner_id == owner_id)
    changed = 0
    for e in db.scalars(stmt):
        e.status = RentStatus.OVERDUE
        changed += 1
    return changed


def apply_increment(db: Session, tenant: Tenant, today: date) -> RentHistory | None:
    """On/after an agreement anniversary, move current_rent to the formula value (idempotent)."""
    if tenant.status != TenantStatus.ACTIVE or not tenant.agreement_start_date:
        return None
    expected = rent_on(tenant, today)
    if expected == tenant.current_rent:
        return None
    effective = latest_anniversary(tenant.agreement_start_date, today)
    exists = db.scalar(select(RentHistory).where(
        RentHistory.tenant_id == tenant.id, RentHistory.effective_from == effective,
        RentHistory.reason == "YEARLY_INCREMENT"))
    if exists:
        tenant.current_rent = expected
        return None
    hist = RentHistory(owner_id=tenant.owner_id, tenant_id=tenant.id, old_rent=tenant.current_rent,
                       new_rent=expected, effective_from=effective, reason="YEARLY_INCREMENT")
    tenant.current_rent = expected
    db.add(hist)
    db.flush()
    return hist


def pending_amount(db: Session, tenant_id: int) -> int:
    v = db.scalar(select(func.coalesce(func.sum(RentEntry.amount_due - RentEntry.amount_paid), 0)).where(
        RentEntry.tenant_id == tenant_id, RentEntry.status != RentStatus.PAID))
    return int(v or 0)
