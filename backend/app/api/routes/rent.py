import logging
from datetime import date

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import Scope
from app.db.models import Channel, Payment, ReminderType, RentEntry, RentStatus, Tenant, TenantStatus
from app.schemas import PaymentIn, PaymentOut, RentEntryOut
from app.services.audit import audit
from app.integrations.email import Attachment, EmailError, send_owner_email
from app.services.excel import autosave_excel
from app.documents.pdf import receipt_pdf
from app.services.rent import compute_status, ensure_entries, refresh_statuses
from app.integrations.storage import get_storage
from app.services.tenants import log_reminder
from app.utils.formatting import fmt_date, inr, month_label, today_ist

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rent", tags=["rent"])


def payment_out(p: Payment) -> PaymentOut:
    out = PaymentOut.model_validate(p)
    out.has_receipt = bool(p.receipt_pdf_path)
    return out


def entry_out(e: RentEntry) -> RentEntryOut:
    t = e.tenant
    return RentEntryOut(
        id=e.id, tenant_id=e.tenant_id, tenant_name=t.full_name, unit_name=t.unit.name if t.unit else None,
        property_name=t.property.name if t.property else None, month=e.month, amount_due=e.amount_due,
        amount_paid=e.amount_paid, status=e.status, due_date=e.due_date,
        payments=[payment_out(p) for p in e.payments],
    )


@router.get("/entries", response_model=list[RentEntryOut])
def list_entries(scope: Scope, month: str | None = None, status_: str | None = Query(None, alias="status"), tenant_id: int | None = None,
                 property_id: int | None = None):
    stmt = scope.select(RentEntry).join(Tenant, Tenant.id == RentEntry.tenant_id)
    if month:
        stmt = stmt.where(RentEntry.month == month)
    if status_:
        stmt = stmt.where(RentEntry.status == status_)
    if tenant_id:
        stmt = stmt.where(RentEntry.tenant_id == tenant_id)
    if property_id:
        stmt = stmt.where(Tenant.property_id == property_id)
    entries = scope.db.scalars(stmt.order_by(RentEntry.due_date.desc(), Tenant.full_name)).all()
    return [entry_out(e) for e in entries]


@router.post("/generate")
def generate_entries(scope: Scope, bg: BackgroundTasks):
    """Create any missing entries for active tenants now (the daily job also does this)."""
    today = today_ist()
    created = 0
    for t in scope.all(Tenant, Tenant.status == TenantStatus.ACTIVE):
        created += len(ensure_entries(scope.db, t, today))
    refresh_statuses(scope.db, today, scope.owner_id)
    scope.db.commit()
    if created:
        bg.add_task(autosave_excel, scope.owner_id)
    return {"created": created}


class EntryUpdate(BaseModel):
    amount_due: int = Field(ge=0, le=100_000_000)


@router.patch("/entries/{entry_id}", response_model=RentEntryOut)
def update_entry(entry_id: int, body: EntryUpdate, scope: Scope, bg: BackgroundTasks):
    e = scope.get_or_404(RentEntry, entry_id, "Rent entry")
    old = e.amount_due
    e.amount_due = body.amount_due
    e.status = compute_status(e, today_ist())
    audit(scope.db, scope.owner_id, "update", "rent_entry", e.id, {"amount_due": [old, body.amount_due]})
    scope.db.commit()
    bg.add_task(autosave_excel, scope.owner_id)
    return entry_out(e)


def _receipt_number(owner_id: int, payment_id: int, paid_on: date) -> str:
    return f"RM{owner_id}-{paid_on:%y%m}-{payment_id:05d}"


@router.post("/entries/{entry_id}/payments", response_model=RentEntryOut, status_code=201)
def add_payment(entry_id: int, body: PaymentIn, scope: Scope, bg: BackgroundTasks):
    e = scope.get_or_404(RentEntry, entry_id, "Rent entry")
    balance = e.amount_due - e.amount_paid
    if balance <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This month is already fully paid")
    if body.amount > balance:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Amount is more than the balance of {inr(balance)}")
    if body.paid_on > today_ist():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Payment date cannot be in the future")
    owner, t = scope.owner, e.tenant
    p = Payment(owner_id=scope.owner_id, rent_entry_id=e.id, amount=body.amount, paid_on=body.paid_on,
                mode=body.mode, reference=(body.reference or "").strip() or None)
    scope.db.add(p)
    scope.db.flush()
    e.amount_paid += body.amount
    e.status = compute_status(e, today_ist())
    p.receipt_number = _receipt_number(scope.owner_id, p.id, body.paid_on)
    pdf = receipt_pdf(
        receipt_number=p.receipt_number, owner_name=owner.name, owner_phone=owner.phone, tenant_name=t.full_name,
        property_name=t.property.name if t.property else "", unit_name=t.unit.name if t.unit else "",
        month_label=month_label(e.month), amount=p.amount, mode=p.mode, reference=p.reference,
        paid_on=fmt_date(p.paid_on), amount_due=e.amount_due, total_paid=e.amount_paid,
    )
    p.receipt_pdf_path = get_storage().save(
        f"owners/{scope.owner_id}/receipts/{p.receipt_number}.pdf", pdf, "application/pdf")
    audit(scope.db, scope.owner_id, "payment", "payment", p.id,
          {"rent_entry_id": e.id, "amount": p.amount, "mode": p.mode})
    scope.db.commit()

    if body.send_receipt and t.email:
        try:
            send_owner_email(
                owner, t.email, f"Rent receipt {p.receipt_number} – {month_label(e.month)}",
                f"Hi {t.full_name},\n\nThank you! We received {inr(p.amount)} towards rent for "
                f"{month_label(e.month)} on {fmt_date(p.paid_on)} ({p.mode}).\n"
                f"Balance for the month: {inr(e.amount_due - e.amount_paid)}.\n\n"
                f"Your receipt is attached.\n\n– {owner.name}",
                attachments=[Attachment(f"{p.receipt_number}.pdf", pdf)],
            )
            log_reminder(scope.db, t, ReminderType.RECEIPT, Channel.EMAIL, "SENT", ref=p.receipt_number)
        except EmailError as err:
            log_reminder(scope.db, t, ReminderType.RECEIPT, Channel.EMAIL, "FAILED", ref=p.receipt_number,
                         error=str(err))
        scope.db.commit()
    bg.add_task(autosave_excel, scope.owner_id)
    scope.db.refresh(e)
    return entry_out(e)


@router.delete("/payments/{payment_id}", response_model=RentEntryOut)
def delete_payment(payment_id: int, scope: Scope, bg: BackgroundTasks):
    p = scope.get_or_404(Payment, payment_id, "Payment")
    e = p.rent_entry
    e.amount_paid = max(0, e.amount_paid - p.amount)
    e.status = compute_status(e, today_ist())
    if p.receipt_pdf_path:
        get_storage().delete(p.receipt_pdf_path)
    audit(scope.db, scope.owner_id, "delete", "payment", p.id, {"amount": p.amount, "rent_entry_id": e.id})
    scope.db.delete(p)
    scope.db.commit()
    scope.db.refresh(e)
    bg.add_task(autosave_excel, scope.owner_id)
    return entry_out(e)


@router.get("/payments/{payment_id}/receipt-url")
def receipt_url(payment_id: int, scope: Scope):
    p = scope.get_or_404(Payment, payment_id, "Payment")
    if not p.receipt_pdf_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No receipt")
    return {"url": get_storage().signed_url(p.receipt_pdf_path), "expires_in": 300}


@router.get("/payments")
def list_payments(scope: Scope, from_: date | None = Query(None, alias="from"), to: date | None = None, limit: int = 200):
    stmt = scope.select(Payment).order_by(Payment.paid_on.desc(), Payment.id.desc()).limit(min(limit, 1000))
    if from_:
        stmt = stmt.where(Payment.paid_on >= from_)
    if to:
        stmt = stmt.where(Payment.paid_on <= to)
    out = []
    for p in scope.db.scalars(stmt):
        e = p.rent_entry
        t = e.tenant
        out.append({**payment_out(p).model_dump(), "month": e.month, "tenant_id": t.id, "tenant_name": t.full_name,
                    "unit_name": t.unit.name if t.unit else None,
                    "property_name": t.property.name if t.property else None, "entry_status": e.status})
    return out


_ = (select, RentStatus)  # keep imports referenced for type checkers
