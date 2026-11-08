from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Channel, Owner, ReminderLog, ReminderType, RentEntry, RentStatus, Tenant
from app.schemas import TenantOut
from app.services.email import EmailError, send_owner_email
from app.services.messages import unit_label, welcome_text
from app.utils.formatting import IST, fmt_date, inr, today_ist
from app.utils.sanitize import html_to_text, sanitize_html
from app.utils.validators import mask_id

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
            from datetime import timezone
            v = v.replace(tzinfo=timezone.utc)
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
    from html import escape

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
