"""Tenant use cases: serialisation, lifecycle (create/approve/reject/vacate/erase), welcome email."""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from html import escape

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BadRequest, ValidationFailed
from app.core.security import encrypt, random_token
from app.db.models import (
    Channel,
    Owner,
    ReminderLog,
    ReminderType,
    RentEntry,
    RentHistory,
    RentStatus,
    Tenant,
    TenantStatus,
    Unit,
)
from app.db.scope import OwnerScope
from app.documents.pdf import settlement_pdf
from app.integrations.email import EmailError, send_owner_email
from app.integrations.storage import get_storage
from app.schemas import ApproveIn, TenantCreate, TenantOut, VacateIn
from app.services.audit import audit
from app.services.messages import unit_label, welcome_text
from app.services.rent import create_entry, ensure_entries, first_month, rebase_rent, rent_on
from app.utils.formatting import IST, fmt_date, inr, month_label, today_ist
from app.utils.sanitize import html_to_text, sanitize_html
from app.utils.validators import mask_id, normalize_id_number, validate_id

log = logging.getLogger(__name__)


def tenant_out(t: Tenant, last_reminded: date | None = None, pending: int = 0) -> TenantOut:
    return TenantOut(
        id=t.id, full_name=t.full_name, phone=t.phone, email=t.email, permanent_address=t.permanent_address,
        id_type=t.id_type, id_masked=mask_id(t.id_type, t.id_last4), has_id_document=bool(t.id_document_path),
        has_photo=bool(t.photo_path), property_id=t.property_id,
        property_name=t.property.name if t.property else None, unit_id=t.unit_id,
        unit_name=t.unit.name if t.unit else None, security_deposit=t.security_deposit,
        agreement_start_date=t.agreement_start_date, agreement_end_date=t.agreement_end_date,
        base_rent=t.base_rent, current_rent=t.current_rent, increment_percent=t.increment_percent,
        due_day=t.due_day, status=t.status, consent_given_at=t.consent_given_at, created_at=t.created_at,
        vacated_at=t.vacated_at, settlement=t.settlement, has_settlement_pdf=bool(t.settlement_pdf_path),
        last_reminded_on=last_reminded, pending_amount=pending,
    )


def tenants_out(db: Session, tenants: list[Tenant]) -> list[TenantOut]:
    ids = [t.id for t in tenants]
    if not ids:
        return []
    last = dict(db.execute(
        select(ReminderLog.tenant_id, func.max(ReminderLog.sent_at)).where(
            ReminderLog.tenant_id.in_(ids), ReminderLog.status == "SENT",
            ReminderLog.type.in_([ReminderType.DUE_SOON, ReminderType.DUE_TODAY, ReminderType.OVERDUE]),
        ).group_by(ReminderLog.tenant_id)
    ).all())
    pending = dict(db.execute(
        select(RentEntry.tenant_id, func.sum(RentEntry.amount_due - RentEntry.amount_paid)).where(
            RentEntry.tenant_id.in_(ids), RentEntry.status != RentStatus.PAID
        ).group_by(RentEntry.tenant_id)
    ).all())

    def _d(v):
        if v is None:
            return None
        if v.tzinfo is None:  # SQLite drops tz info; values are stored in UTC
            v = v.replace(tzinfo=UTC)
        return v.astimezone(IST).date()

    return [tenant_out(t, _d(last.get(t.id)), int(pending.get(t.id) or 0)) for t in tenants]


def log_reminder(db: Session, tenant: Tenant, type_: str, channel: str, status: str, ref: str | None = None,
                 error: str | None = None, today: date | None = None) -> ReminderLog:
    entry = ReminderLog(owner_id=tenant.owner_id, tenant_id=tenant.id, type=type_, channel=channel, ref=ref,
                        status=status, error=(error or "")[:500] or None, sent_on=today or today_ist())
    db.add(entry)
    return entry


def send_welcome(db: Session, owner: Owner, tenant: Tenant) -> bool:
    if not tenant.email:
        return False
    rules_html = sanitize_html(tenant.property.house_rules) if tenant.property else None
    intro = welcome_text(db, owner, tenant)
    text = (
        f"{intro}\n\nYour details:\n- Unit: {unit_label(tenant)}\n- Monthly rent: {inr(tenant.current_rent)}\n"
        f"- Rent due on: day {tenant.due_day} of every month\n- Security deposit: {inr(tenant.security_deposit)}\n"
        f"- Agreement start: {fmt_date(tenant.agreement_start_date)}\n"
    )
    if rules_html:
        text += f"\nHouse rules:\n{html_to_text(rules_html)}\n"

    html = (
        f"<p>{escape(intro)}</p><ul><li>Unit: {escape(unit_label(tenant))}</li>"
        f"<li>Monthly rent: {inr(tenant.current_rent)}</li>"
        f"<li>Rent due on: day {tenant.due_day} of every month</li>"
        f"<li>Security deposit: {inr(tenant.security_deposit)}</li>"
        f"<li>Agreement start: {fmt_date(tenant.agreement_start_date)}</li></ul>"
    )
    if rules_html:
        html += f"<h3>House rules</h3>{rules_html}"
    try:
        send_owner_email(owner, tenant.email, f"Welcome to {unit_label(tenant)}", text, html)
        log_reminder(db, tenant, ReminderType.WELCOME, Channel.EMAIL, "SENT", ref="welcome")
        return True
    except EmailError as e:
        log_reminder(db, tenant, ReminderType.WELCOME, Channel.EMAIL, "FAILED", ref="welcome", error=str(e))
        return False


# ---------------------------------------------------------------------------
# Tenant lifecycle (business rules). Routers call these; they never touch HTTP.
# ---------------------------------------------------------------------------
def _start_ledger(scope: OwnerScope, t: Tenant) -> None:
    today = today_ist()
    create_entry(scope.db, t, first_month(t, today), today)
    ensure_entries(scope.db, t, today)


def create_tenant(scope: OwnerScope, body: TenantCreate) -> Tenant:
    """Owner-entered tenant who already lives in the property (ID optional)."""
    unit = scope.get_or_404(Unit, body.unit_id, "Unit")
    t = Tenant(owner_id=scope.owner_id, property_id=unit.property_id, unit_id=unit.id,
               full_name=body.full_name.strip(), phone=body.phone, email=body.email,
               permanent_address=body.permanent_address, security_deposit=body.security_deposit,
               agreement_start_date=body.agreement_start_date, agreement_end_date=body.agreement_end_date,
               due_day=body.due_day, increment_percent=body.increment_percent, status=TenantStatus.ACTIVE)
    if body.id_number:
        if not body.id_type:
            raise ValidationFailed("Choose the ID type", {"id_type": "Choose the ID type"})
        num = normalize_id_number(body.id_type, body.id_number)
        err = validate_id(body.id_type, num)
        if err:
            raise ValidationFailed(err, {"id_number": err})
        t.id_type, t.id_number_encrypted, t.id_last4 = body.id_type, encrypt(num), num[-4:]
    # base_rent is the rent at agreement start; the formula derives today's rent.
    t.base_rent = body.base_rent
    t.rent_base_date = body.agreement_start_date
    t.current_rent = rent_on(t, today_ist())
    scope.db.add(t)
    scope.db.flush()
    _start_ledger(scope, t)
    audit(scope.db, scope.owner_id, "create", "tenant", t.id, {"source": "owner"})
    scope.db.commit()
    return t


def update_tenant(scope: OwnerScope, t: Tenant, data: dict) -> Tenant:
    if data.get("unit_id") is not None:
        t.property_id = scope.get_or_404(Unit, data["unit_id"], "Unit").property_id
    if "increment_percent" in data and data["increment_percent"] != t.increment_percent:
        rebase_rent(t, t.current_rent or t.base_rent, today_ist())
    for k, v in data.items():
        setattr(t, k, v)
    audit(scope.db, scope.owner_id, "update", "tenant", t.id, {"fields": list(data)})
    scope.db.commit()
    return t


def approve(scope: OwnerScope, t: Tenant, body: ApproveIn) -> Tenant:
    if t.status != TenantStatus.PENDING_APPROVAL:
        raise BadRequest("Only pending tenants can be approved")
    if body.unit_id is not None:
        unit = scope.get_or_404(Unit, body.unit_id, "Unit")
        t.unit_id, t.property_id = unit.id, unit.property_id
    if not t.unit_id:
        raise BadRequest("Choose the unit for this tenant")
    if body.agreement_end_date and body.agreement_end_date <= body.agreement_start_date:
        raise BadRequest("Agreement end date must be after the start date")
    t.base_rent = body.base_rent
    t.security_deposit = body.security_deposit
    t.agreement_start_date = body.agreement_start_date
    t.agreement_end_date = body.agreement_end_date
    t.rent_base_date = body.agreement_start_date
    t.due_day = body.due_day
    t.increment_percent = body.increment_percent
    t.status = TenantStatus.ACTIVE
    t.current_rent = rent_on(t, today_ist())
    scope.db.flush()
    _start_ledger(scope, t)
    audit(scope.db, scope.owner_id, "approve", "tenant", t.id)
    scope.db.commit()
    scope.db.refresh(t)
    send_welcome(scope.db, scope.owner, t)
    scope.db.commit()
    return t


def delete_documents(t: Tenant) -> bool:
    """Remove the ID document and photo from storage (caller commits)."""
    storage = get_storage()
    deleted = False
    for attr in ("id_document_path", "photo_path"):
        path = getattr(t, attr)
        if path:
            storage.delete(path)
            setattr(t, attr, None)
            deleted = True
    if deleted:
        t.id_documents_deleted_at = datetime.now(UTC)
    return deleted


def reject(scope: OwnerScope, t: Tenant) -> Tenant:
    if t.status != TenantStatus.PENDING_APPROVAL:
        raise BadRequest("Only pending tenants can be rejected")
    t.status = TenantStatus.REJECTED
    delete_documents(t)  # a rejected applicant's ID is not needed
    audit(scope.db, scope.owner_id, "reject", "tenant", t.id)
    scope.db.commit()
    return t


def remove_documents(scope: OwnerScope, t: Tenant) -> Tenant:
    if t.status == TenantStatus.ACTIVE:
        raise BadRequest("ID documents can be deleted after the tenant vacates")
    delete_documents(t)
    audit(scope.db, scope.owner_id, "delete", "id_document", t.id)
    scope.db.commit()
    return t


def erase_personal_data(scope: OwnerScope, t: Tenant) -> Tenant:
    """DPDP right to erasure: anonymise a former tenant's personal data.

    Rent entries and payments are kept (receipts are financial records) but no
    longer identify the person.
    """
    if t.status in (TenantStatus.ACTIVE, TenantStatus.PENDING_APPROVAL):
        raise BadRequest("Vacate or reject the tenant before erasing their data")
    delete_documents(t)
    if t.settlement_pdf_path:
        get_storage().delete(t.settlement_pdf_path)
        t.settlement_pdf_path = None
    t.full_name = f"Erased tenant #{t.id}"
    t.phone = ""
    t.email = None
    t.permanent_address = None
    t.id_type = t.id_number_encrypted = t.id_last4 = None
    audit(scope.db, scope.owner_id, "erase", "tenant", t.id)
    scope.db.commit()
    return t


def delete_tenant(scope: OwnerScope, t: Tenant) -> None:
    if t.status == TenantStatus.ACTIVE:
        raise BadRequest("Vacate the tenant before deleting")
    delete_documents(t)
    audit(scope.db, scope.owner_id, "delete", "tenant", t.id)
    scope.db.delete(t)
    scope.db.commit()


def change_rent(scope: OwnerScope, t: Tenant, new_rent: int) -> Tenant:
    if t.status != TenantStatus.ACTIVE:
        raise BadRequest("Tenant is not active")
    today = today_ist()
    old = t.current_rent
    rebase_rent(t, new_rent, today)
    scope.db.add(RentHistory(owner_id=t.owner_id, tenant_id=t.id, old_rent=old, new_rent=new_rent,
                             effective_from=today, reason="MANUAL"))
    audit(scope.db, scope.owner_id, "update", "tenant", t.id, {"rent": [old, new_rent]})
    scope.db.commit()
    return t


def renew(scope: OwnerScope, t: Tenant, new_end: date) -> Tenant:
    if t.agreement_start_date and new_end <= t.agreement_start_date:
        raise BadRequest("New end date must be after the agreement start")
    old = t.agreement_end_date
    t.agreement_end_date = new_end
    audit(scope.db, scope.owner_id, "update", "tenant", t.id,
          {"renewed": [old.isoformat() if old else None, new_end.isoformat()]})
    scope.db.commit()
    return t


def settlement(scope: OwnerScope, t: Tenant, body: VacateIn) -> dict:
    """Deposit - pending rent (up to the vacate month) - deductions."""
    vacate_month = body.vacate_date.strftime("%Y-%m")
    unpaid = scope.all(RentEntry, RentEntry.tenant_id == t.id, RentEntry.status != RentStatus.PAID,
                       RentEntry.month <= vacate_month, order_by=RentEntry.month)
    pending_months = [{"month": e.month, "label": month_label(e.month), "amount": e.amount_due - e.amount_paid}
                      for e in unpaid if e.amount_due > e.amount_paid]
    pending = sum(p["amount"] for p in pending_months)
    deductions = [d.model_dump() for d in body.deductions]
    total_ded = sum(d["amount"] for d in deductions)
    return {
        "vacate_date": body.vacate_date.isoformat(), "deposit": t.security_deposit,
        "pending_rent": pending, "pending_months": pending_months, "deductions": deductions,
        "total_deductions": total_ded, "refund": t.security_deposit - pending - total_ded,
        "notes": body.notes,
    }


def vacate(scope: OwnerScope, t: Tenant, body: VacateIn) -> Tenant:
    if t.status != TenantStatus.ACTIVE:
        raise BadRequest("Only active tenants can be vacated")
    st = settlement(scope, t, body)
    # Drop unpaid entries pre-generated for months after the move-out.
    for e in scope.all(RentEntry, RentEntry.tenant_id == t.id,
                       RentEntry.month > body.vacate_date.strftime("%Y-%m"), RentEntry.amount_paid == 0):
        scope.db.delete(e)
    pdf = settlement_pdf(
        owner_name=scope.owner.name, tenant_name=t.full_name,
        property_name=t.property.name if t.property else "", unit_name=t.unit.name if t.unit else "",
        agreement_start=fmt_date(t.agreement_start_date), vacate_date=fmt_date(body.vacate_date),
        deposit=st["deposit"], pending_rent=st["pending_rent"],
        pending_months=[(p["label"], p["amount"]) for p in st["pending_months"]],
        deductions=[(d["label"], d["amount"]) for d in st["deductions"]], refund=st["refund"],
        notes=body.notes, generated_on=fmt_date(today_ist()),
    )
    t.settlement_pdf_path = get_storage().save(
        f"owners/{t.owner_id}/tenants/{t.id}/settlement-{random_token(6)}.pdf", pdf, "application/pdf")
    t.status = TenantStatus.VACATED
    t.vacated_at = body.vacate_date
    t.settlement = st
    audit(scope.db, scope.owner_id, "update", "tenant", t.id,
          {"vacated": body.vacate_date.isoformat(), "refund": st["refund"]})
    scope.db.commit()
    return t
