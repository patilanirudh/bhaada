"""Rent ledger use cases: serialising entries, recording/deleting payments, receipts."""
from __future__ import annotations

import logging
from datetime import date

from app.core.errors import BadRequest
from app.db.models import Channel, Payment, ReminderType, RentEntry, Tenant, TenantStatus
from app.db.scope import OwnerScope
from app.documents.pdf import receipt_pdf
from app.integrations.email import Attachment, EmailError, send_owner_email
from app.integrations.storage import StorageError, get_storage
from app.schemas import PaymentIn, PaymentOut, RentEntryOut
from app.services.audit import audit
from app.services.rent import compute_status, ensure_entries, refresh_statuses
from app.services.tenants import log_reminder
from app.utils.formatting import fmt_date, inr, month_label, today_ist

log = logging.getLogger(__name__)


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


def generate_entries(scope: OwnerScope) -> int:
    """Create any missing monthly entries for active tenants (the daily job also does this)."""
    today = today_ist()
    created = sum(len(ensure_entries(scope.db, t, today))
                  for t in scope.all(Tenant, Tenant.status == TenantStatus.ACTIVE))
    refresh_statuses(scope.db, today, scope.owner_id)
    scope.db.commit()
    return created


def set_amount_due(scope: OwnerScope, e: RentEntry, amount_due: int) -> RentEntry:
    old = e.amount_due
    e.amount_due = amount_due
    e.status = compute_status(e, today_ist())
    audit(scope.db, scope.owner_id, "update", "rent_entry", e.id, {"amount_due": [old, amount_due]})
    scope.db.commit()
    return e


def receipt_number(owner_id: int, payment_id: int, paid_on: date) -> str:
    return f"RM{owner_id}-{paid_on:%y%m}-{payment_id:05d}"


def record_payment(scope: OwnerScope, e: RentEntry, body: PaymentIn) -> RentEntry:
    """Record a full/partial payment, generate the PDF receipt and (optionally) email it."""
    balance = e.amount_due - e.amount_paid
    if balance <= 0:
        raise BadRequest("This month is already fully paid")
    if body.amount > balance:
        raise BadRequest(f"Amount is more than the balance of {inr(balance)}")
    if body.paid_on > today_ist():
        raise BadRequest("Payment date cannot be in the future")
    owner, t = scope.owner, e.tenant
    p = Payment(owner_id=scope.owner_id, rent_entry_id=e.id, amount=body.amount, paid_on=body.paid_on,
                mode=body.mode, reference=(body.reference or "").strip() or None)
    scope.db.add(p)
    scope.db.flush()
    e.amount_paid += body.amount
    e.status = compute_status(e, today_ist())
    p.receipt_number = receipt_number(scope.owner_id, p.id, body.paid_on)
    pdf = receipt_pdf(
        receipt_number=p.receipt_number, owner_name=owner.name, owner_phone=owner.phone, tenant_name=t.full_name,
        property_name=t.property.name if t.property else "", unit_name=t.unit.name if t.unit else "",
        month_label=month_label(e.month), amount=p.amount, mode=p.mode, reference=p.reference,
        paid_on=fmt_date(p.paid_on), amount_due=e.amount_due, total_paid=e.amount_paid,
    )
    try:
        p.receipt_pdf_path = get_storage().save(
            f"owners/{scope.owner_id}/receipts/{p.receipt_number}.pdf", pdf, "application/pdf")
    except StorageError as err:
        # The payment is what matters; the receipt is still emailed and can be regenerated.
        log.error("Receipt upload failed for payment %s: %s", p.id, err)
    audit(scope.db, scope.owner_id, "payment", "payment", p.id,
          {"rent_entry_id": e.id, "amount": p.amount, "mode": p.mode})
    scope.db.commit()

    if body.send_receipt and t.email:
        _email_receipt(scope, t, e, p, pdf)
    scope.db.refresh(e)
    return e


def _email_receipt(scope: OwnerScope, t: Tenant, e: RentEntry, p: Payment, pdf: bytes) -> None:
    owner = scope.owner
    try:
        send_owner_email(
            owner, t.email, f"Rent receipt {p.receipt_number} - {month_label(e.month)}",
            f"Hi {t.full_name},\n\nThank you! We received {inr(p.amount)} towards rent for "
            f"{month_label(e.month)} on {fmt_date(p.paid_on)} ({p.mode}).\n"
            f"Balance for the month: {inr(e.amount_due - e.amount_paid)}.\n\n"
            f"Your receipt is attached.\n\n- {owner.name}",
            attachments=[Attachment(f"{p.receipt_number}.pdf", pdf)],
        )
        log_reminder(scope.db, t, ReminderType.RECEIPT, Channel.EMAIL, "SENT", ref=p.receipt_number)
    except EmailError as err:
        log_reminder(scope.db, t, ReminderType.RECEIPT, Channel.EMAIL, "FAILED", ref=p.receipt_number,
                     error=str(err))
    scope.db.commit()


def delete_payment(scope: OwnerScope, p: Payment) -> RentEntry:
    e = p.rent_entry
    e.amount_paid = max(0, e.amount_paid - p.amount)
    e.status = compute_status(e, today_ist())
    if p.receipt_pdf_path:
        get_storage().delete(p.receipt_pdf_path)
    audit(scope.db, scope.owner_id, "delete", "payment", p.id, {"amount": p.amount, "rent_entry_id": e.id})
    scope.db.delete(p)
    scope.db.commit()
    scope.db.refresh(e)
    return e
