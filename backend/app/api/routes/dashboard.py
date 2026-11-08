from datetime import date, timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import Scope
from app.db.models import RentEntry, RentStatus, Tenant, TenantStatus
from app.api.routes.reminders import due_items, increment_items
from app.services.rent import month_str
from app.utils.formatting import month_label, today_ist

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _last_12_months(today: date) -> list[str]:
    months = []
    m = date(today.year, today.month, 1)
    for _ in range(12):
        months.insert(0, month_str(m))
        m = (m - timedelta(days=1)).replace(day=1)
    return months


@router.get("")
def dashboard(scope: Scope):
    today = today_ist()
    cur = month_str(today)
    db = scope.db

    months = _last_12_months(today)
    rows = db.execute(
        select(RentEntry.month, func.sum(RentEntry.amount_due), func.sum(RentEntry.amount_paid))
        .where(RentEntry.owner_id == scope.owner_id, RentEntry.month.in_(months)).group_by(RentEntry.month)
    ).all()
    agg = {m: (int(d or 0), int(p or 0)) for m, d, p in rows}
    chart = [{"month": m, "label": month_label(m), "expected": agg.get(m, (0, 0))[0],
              "collected": agg.get(m, (0, 0))[1]} for m in months]
    expected, collected = agg.get(cur, (0, 0))
    overdue_count = db.scalar(select(func.count()).select_from(RentEntry).where(
        RentEntry.owner_id == scope.owner_id, RentEntry.status == RentStatus.OVERDUE)) or 0
    overdue_amount = db.scalar(select(func.coalesce(func.sum(RentEntry.amount_due - RentEntry.amount_paid), 0)).where(
        RentEntry.owner_id == scope.owner_id, RentEntry.status == RentStatus.OVERDUE)) or 0

    dues = due_items(scope, today, within_days=0)
    pending = scope.all(Tenant, Tenant.status == TenantStatus.PENDING_APPROVAL, order_by=Tenant.created_at)
    expiring = []
    for t in scope.all(Tenant, Tenant.status == TenantStatus.ACTIVE, Tenant.agreement_end_date.is_not(None),
                       Tenant.agreement_end_date <= today + timedelta(days=30), order_by=Tenant.agreement_end_date):
        expiring.append({"tenant_id": t.id, "tenant_name": t.full_name, "unit_name": t.unit.name if t.unit else None,
                         "end_date": t.agreement_end_date.isoformat(),
                         "days_left": (t.agreement_end_date - today).days})
    active_count = db.scalar(select(func.count()).select_from(Tenant).where(
        Tenant.owner_id == scope.owner_id, Tenant.status == TenantStatus.ACTIVE)) or 0

    return {
        "today": today.isoformat(),
        "month": cur,
        "month_label": month_label(cur),
        "cards": {"expected": expected, "collected": collected, "pending": max(0, expected - collected),
                  "overdue_count": overdue_count, "overdue_amount": int(overdue_amount),
                  "active_tenants": active_count},
        "actions": {
            "due_today": [d for d in dues if d["type"] == "DUE_TODAY"],
            "overdue": [d for d in dues if d["type"] == "OVERDUE"],
            "pending_approvals": [{"tenant_id": t.id, "tenant_name": t.full_name, "phone": t.phone,
                                   "property_name": t.property.name if t.property else None,
                                   "unit_name": t.unit.name if t.unit else None,
                                   "created_at": t.created_at.isoformat()} for t in pending],
            "upcoming_increments": increment_items(scope, today),
            "expiring_agreements": expiring,
        },
        "chart": chart,
        "gmail_configured": bool(scope.owner.gmail_address and scope.owner.gmail_app_password_encrypted),
        "upi_configured": bool(scope.owner.upi_id),
    }
