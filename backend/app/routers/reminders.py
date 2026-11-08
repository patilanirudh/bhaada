"""WhatsApp two-tap reminders (wa.me links), queue mode and reminder logs."""
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.deps import Scope
from app.models import (
    Channel,
    ReminderLog,
    ReminderType,
    RentEntry,
    RentStatus,
    Tenant,
    TenantStatus,
)
from app.schemas import ReminderLogOut, WhatsAppLogIn
from app.services.audit import audit
from app.services.messages import increment_text, rent_reminder_text, welcome_text
from app.services.rent import next_anniversary, rent_on
from app.services.tenants import log_reminder
from app.services.whatsapp import get_sender
from app.utils.formatting import today_ist

router = APIRouter(prefix="/api/reminders", tags=["reminders"])


def rent_type(e: RentEntry, today: date) -> str:
    if e.due_date > today:
        return ReminderType.DUE_SOON
    if e.due_date == today:
        return ReminderType.DUE_TODAY
    return ReminderType.OVERDUE


def last_whatsapp(scope: Scope, tenant_ids: list[int], types: list[str]) -> dict[int, date]:
    if not tenant_ids:
        return {}
    rows = scope.db.execute(
        select(ReminderLog.tenant_id, func.max(ReminderLog.sent_on)).where(
            ReminderLog.owner_id == scope.owner_id, ReminderLog.tenant_id.in_(tenant_ids),
            ReminderLog.channel == Channel.WHATSAPP_MANUAL, ReminderLog.type.in_(types),
        ).group_by(ReminderLog.tenant_id)
    ).all()
    return dict(rows)


def wa_item(scope: Scope, t: Tenant, text: str, type_: str, ref: str | None, extra: dict | None = None) -> dict:
    result = get_sender().send(t.phone, text)
    return {"tenant_id": t.id, "tenant_name": t.full_name, "phone": t.phone,
            "unit_name": t.unit.name if t.unit else None, "property_name": t.property.name if t.property else None,
            "text": text, "link": result.link, "type": type_, "ref": ref, **(extra or {})}


def due_items(scope: Scope, today: date, within_days: int = 3) -> list[dict]:
    """One item per tenant: their earliest unpaid entry due within ``within_days`` (or overdue)."""
    entries = scope.db.scalars(
        scope.select(RentEntry).join(Tenant, Tenant.id == RentEntry.tenant_id).where(
            RentEntry.status != RentStatus.PAID, Tenant.status == TenantStatus.ACTIVE,
            RentEntry.due_date <= today + timedelta(days=within_days),
        ).order_by(RentEntry.due_date)
    ).all()
    seen: set[int] = set()
    items = []
    for e in entries:
        if e.tenant_id in seen:
            continue
        seen.add(e.tenant_id)
        t = e.tenant
        items.append(wa_item(scope, t, rent_reminder_text(scope.db, scope.owner, t, e, today), rent_type(e, today),
                             e.month, {"rent_entry_id": e.id, "month": e.month, "due_date": e.due_date.isoformat(),
                                       "balance": e.amount_due - e.amount_paid}))
    last = last_whatsapp(scope, list(seen), [ReminderType.DUE_SOON, ReminderType.DUE_TODAY, ReminderType.OVERDUE])
    for it in items:
        it["last_whatsapp_on"] = last.get(it["tenant_id"])
    return items


def increment_items(scope: Scope, today: date) -> list[dict]:
    items = []
    for t in scope.all(Tenant, Tenant.status == TenantStatus.ACTIVE):
        if not t.agreement_start_date:
            continue
        anniv = next_anniversary(t.agreement_start_date, today)
        if not 0 < (anniv - today).days <= 30:
            continue
        new = rent_on(t, anniv)
        if new == t.current_rent:
            continue
        text = increment_text(scope.db, scope.owner, t, t.current_rent, new, anniv)
        items.append(wa_item(scope, t, text, ReminderType.INCREMENT_NOTICE, anniv.isoformat(),
                             {"old_rent": t.current_rent, "new_rent": new, "effective_date": anniv.isoformat()}))
    return items


@router.get("/whatsapp/queue")
def whatsapp_queue(scope: Scope, kind: str = "due"):
    today = today_ist()
    if kind == "due":
        items = due_items(scope, today)
    elif kind == "increment":
        items = increment_items(scope, today)
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown queue")
    return {"kind": kind, "items": items}


@router.get("/whatsapp/tenant/{tenant_id}")
def whatsapp_for_tenant(tenant_id: int, scope: Scope, kind: str = "rent"):
    """Message + wa.me link for a single tenant."""
    t = scope.get_or_404(Tenant, tenant_id, "Tenant")
    today = today_ist()
    if kind == "rent":
        e = scope.db.scalar(scope.select(RentEntry).where(
            RentEntry.tenant_id == t.id, RentEntry.status != RentStatus.PAID).order_by(RentEntry.due_date))
        if not e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No pending rent for this tenant")
        return wa_item(scope, t, rent_reminder_text(scope.db, scope.owner, t, e, today), rent_type(e, today),
                       e.month, {"rent_entry_id": e.id})
    if kind == "welcome":
        return wa_item(scope, t, welcome_text(scope.db, scope.owner, t), ReminderType.WELCOME, "welcome")
    if kind == "increment":
        items = [i for i in increment_items(scope, today) if i["tenant_id"] == t.id]
        if not items:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No rent increase in the next 30 days")
        return items[0]
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown message type")


@router.post("/whatsapp/log", response_model=ReminderLogOut, status_code=201)
def log_whatsapp(body: WhatsAppLogIn, scope: Scope):
    t = scope.get_or_404(Tenant, body.tenant_id, "Tenant")
    entry = log_reminder(scope.db, t, body.type, Channel.WHATSAPP_MANUAL, "SENT", ref=body.ref)
    audit(scope.db, scope.owner_id, "remind", "tenant", t.id, {"channel": "WHATSAPP_MANUAL", "type": body.type})
    scope.db.commit()
    return entry


@router.get("/logs", response_model=list[ReminderLogOut])
def logs(scope: Scope, limit: int = 100):
    stmt = scope.select(ReminderLog).order_by(ReminderLog.sent_at.desc()).limit(min(limit, 500))
    return list(scope.db.scalars(stmt))
