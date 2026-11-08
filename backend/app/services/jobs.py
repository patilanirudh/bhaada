"""The daily job (run once a day at 08:00 IST via POST /api/jobs/run-daily).

Idempotent: every email is recorded in ReminderLog with a dedupe ``ref``, and an
email is only sent if no SENT row exists for (tenant, type, ref) — so running
the job twice on the same day sends nothing new. Failed sends are logged as
FAILED and retried on the next run. A failure never stops the job.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from html import escape

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    Channel,
    Owner,
    ReminderLog,
    ReminderType,
    RentEntry,
    RentStatus,
    Tenant,
    TenantStatus,
)
from app.integrations.email import (
    EmailError,
    notify_owner,
    owner_credentials,
    send_owner_email,
    system_credentials,
)
from app.services.excel import autosave_excel
from app.services.messages import increment_text, rent_reminder_text, unit_label, upi_link
from app.services.rent import apply_increment, ensure_entries, next_anniversary, refresh_statuses, rent_on
from app.services.tenants import log_reminder
from app.integrations.storage import get_storage
from app.utils.formatting import fmt_date, inr, month_label

log = logging.getLogger(__name__)

OVERDUE_EVERY_DAYS = 3
DUE_SOON_DAYS = 3
INCREMENT_NOTICE_DAYS = 30
EXPIRY_NOTICE_DAYS = (30, 7)
ID_RETENTION_DAYS = 90


@dataclass
class JobSummary:
    date: str = ""
    owners: int = 0
    entries_created: int = 0
    marked_overdue: int = 0
    increments_applied: int = 0
    emails_sent: int = 0
    emails_failed: int = 0
    emails_skipped_no_gmail: int = 0
    documents_deleted: int = 0
    errors: list[str] = field(default_factory=list)


def _sent(db: Session, tenant_id: int, type_: str, ref: str) -> bool:
    return db.scalar(select(func.count()).select_from(ReminderLog).where(
        ReminderLog.tenant_id == tenant_id, ReminderLog.type == type_, ReminderLog.ref == ref,
        ReminderLog.channel == Channel.EMAIL, ReminderLog.status == "SENT")) > 0


def _last_sent_on(db: Session, tenant_id: int, type_: str, ref: str) -> date | None:
    return db.scalar(select(func.max(ReminderLog.sent_on)).where(
        ReminderLog.tenant_id == tenant_id, ReminderLog.type == type_, ReminderLog.ref == ref,
        ReminderLog.channel == Channel.EMAIL, ReminderLog.status == "SENT"))


class _OwnerMailer:
    """Sends from one owner's Gmail, logs each attempt and stops after a login failure."""

    def __init__(self, db: Session, owner: Owner, summary: JobSummary, today: date):
        self.db, self.owner, self.summary, self.today = db, owner, summary, today
        self.broken = False
        self.configured = (owner_credentials(owner) is not None or system_credentials() is not None
                           or get_settings().email_backend != "smtp")

    def send(self, tenant: Tenant, type_: str, ref: str, subject: str, text: str, html: str | None = None) -> bool:
        if not tenant.email:
            return False
        if not self.configured:
            self.summary.emails_skipped_no_gmail += 1
            return False
        if self.broken:
            return False
        try:
            send_owner_email(self.owner, tenant.email, subject, text, html)
            log_reminder(self.db, tenant, type_, Channel.EMAIL, "SENT", ref=ref, today=self.today)
            self.summary.emails_sent += 1
            ok = True
        except EmailError as e:
            log_reminder(self.db, tenant, type_, Channel.EMAIL, "FAILED", ref=ref, error=str(e), today=self.today)
            self.summary.emails_failed += 1
            if "rejected the login" in str(e) or "not configured" in str(e):
                self.broken = True
            ok = False
        self.db.commit()
        return ok


def _rent_email(db: Session, owner: Owner, t: Tenant, e: RentEntry, today: date) -> tuple[str, str, str]:
    text = rent_reminder_text(db, owner, t, e, today)
    balance = e.amount_due - e.amount_paid
    link = upi_link(owner, balance, e.month)
    overdue = e.due_date < today
    subject = (f"Rent overdue: {inr(balance)} for {month_label(e.month)}" if overdue
               else f"Rent reminder: {inr(balance)} due on {fmt_date(e.due_date)}")
    body = (f"{text}\n\nAmount: {inr(balance)}\nMonth: {month_label(e.month)}\nUnit: {unit_label(t)}\n"
            f"Due date: {fmt_date(e.due_date)}\n")
    html = (f"<p>{escape(text)}</p><table cellpadding='4'>"
            f"<tr><td><b>Amount</b></td><td>{inr(balance)}</td></tr>"
            f"<tr><td><b>Month</b></td><td>{month_label(e.month)}</td></tr>"
            f"<tr><td><b>Unit</b></td><td>{escape(unit_label(t))}</td></tr>"
            f"<tr><td><b>Due date</b></td><td>{fmt_date(e.due_date)}</td></tr></table>")
    if link:
        body += f"\nPay by UPI (tap on your phone): {link}\nUPI ID: {owner.upi_id}\n"
        html += (f"<p><a href=\"{escape(link)}\" style=\"background:#059669;color:#fff;padding:10px 16px;"
                 f"border-radius:6px;text-decoration:none\">Pay {inr(balance)} via UPI</a></p>"
                 f"<p>UPI ID: {escape(owner.upi_id or '')}</p>")
    return subject, body, html


def rent_reminder_type(e: RentEntry, today: date, db: Session, tenant_id: int) -> str | None:
    """Which reminder (if any) is due today for this unpaid entry."""
    days_to_due = (e.due_date - today).days
    if 0 < days_to_due <= DUE_SOON_DAYS:
        return None if _sent(db, tenant_id, ReminderType.DUE_SOON, e.month) else ReminderType.DUE_SOON
    if days_to_due == 0:
        return None if _sent(db, tenant_id, ReminderType.DUE_TODAY, e.month) else ReminderType.DUE_TODAY
    if days_to_due < 0 and -days_to_due >= OVERDUE_EVERY_DAYS:
        last = _last_sent_on(db, tenant_id, ReminderType.OVERDUE, e.month)
        if last is None or (today - last).days >= OVERDUE_EVERY_DAYS:
            return ReminderType.OVERDUE
    return None


def _process_owner(db: Session, owner: Owner, today: date, s: JobSummary) -> None:
    mailer = _OwnerMailer(db, owner, s, today)
    tenants = list(db.scalars(select(Tenant).where(Tenant.owner_id == owner.id,
                                                   Tenant.status == TenantStatus.ACTIVE)))
    changed = False

    # 1) yearly increments + 2) ledger entries + 3) overdue statuses
    for t in tenants:
        if apply_increment(db, t, today):
            s.increments_applied += 1
            changed = True
        created = ensure_entries(db, t, today)
        s.entries_created += len(created)
        changed = changed or bool(created)
    n = refresh_statuses(db, today, owner.id)
    s.marked_overdue += n
    changed = changed or bool(n)
    db.commit()

    # 4) rent reminder emails
    tmap = {t.id: t for t in tenants}
    unpaid = db.scalars(select(RentEntry).where(
        RentEntry.owner_id == owner.id, RentEntry.status != RentStatus.PAID,
        RentEntry.tenant_id.in_(list(tmap) or [0])).order_by(RentEntry.due_date))
    for e in list(unpaid):
        t = tmap[e.tenant_id]
        type_ = rent_reminder_type(e, today, db, t.id)
        if type_:
            subject, body, html = _rent_email(db, owner, t, e, today)
            mailer.send(t, type_, e.month, subject, body, html)

    # 5) yearly increment notices (30 days before the anniversary)
    for t in tenants:
        if not t.agreement_start_date:
            continue
        anniv = next_anniversary(t.agreement_start_date, today)
        days = (anniv - today).days
        if not 0 < days <= INCREMENT_NOTICE_DAYS:
            continue
        new = rent_on(t, anniv)
        if new == t.current_rent or _sent(db, t.id, ReminderType.INCREMENT_NOTICE, anniv.isoformat()):
            continue
        text = increment_text(db, owner, t, t.current_rent, new, anniv)
        mailer.send(t, ReminderType.INCREMENT_NOTICE, anniv.isoformat(),
                    f"Rent revision from {fmt_date(anniv)}",
                    f"{text}\n\nCurrent rent: {inr(t.current_rent)}\nNew rent: {inr(new)}\n"
                    f"Effective from: {fmt_date(anniv)}\n")

    # 6) agreement expiry notices to the owner (30 and 7 days before)
    for t in tenants:
        if not t.agreement_end_date:
            continue
        days_left = (t.agreement_end_date - today).days
        bucket = next((d for d in sorted(EXPIRY_NOTICE_DAYS) if 0 <= days_left <= d), None)
        if bucket is None:
            continue
        ref = f"{bucket}:{t.agreement_end_date.isoformat()}"
        if _sent(db, t.id, ReminderType.AGREEMENT_EXPIRY, ref):
            continue
        err = notify_owner(owner, f"Agreement ending in {days_left} days: {t.full_name}",
                           f"Hi {owner.name},\n\nThe rental agreement of {t.full_name} ({unit_label(t)}) ends on "
                           f"{fmt_date(t.agreement_end_date)} ({days_left} days from today).\n"
                           f"Open Rent Manager and tap 'Renew' to extend it, or plan the move-out.\n\n"
                           f"{get_settings().frontend_url.rstrip('/')}/tenants/{t.id}")
        log_reminder(db, t, ReminderType.AGREEMENT_EXPIRY, Channel.EMAIL, "FAILED" if err else "SENT",
                     ref=ref, error=err, today=today)
        if err:
            s.emails_failed += 1
        else:
            s.emails_sent += 1
        db.commit()

    # 7) delete ID documents 90 days after move-out
    cutoff = today - timedelta(days=ID_RETENTION_DAYS)
    storage = get_storage()
    for t in db.scalars(select(Tenant).where(
            Tenant.owner_id == owner.id, Tenant.status == TenantStatus.VACATED, Tenant.vacated_at <= cutoff,
            (Tenant.id_document_path.is_not(None)) | (Tenant.photo_path.is_not(None)))):
        from datetime import datetime, timezone

        for attr in ("id_document_path", "photo_path"):
            if getattr(t, attr):
                try:
                    storage.delete(getattr(t, attr))
                except Exception as exc:  # retry next run
                    s.errors.append(f"doc delete tenant {t.id}: {exc.__class__.__name__}")
                    continue
                setattr(t, attr, None)
        t.id_documents_deleted_at = datetime.now(timezone.utc)
        s.documents_deleted += 1
    db.commit()

    if changed:
        autosave_excel(owner.id)


def run_daily(db: Session, today: date) -> dict:
    s = JobSummary(date=today.isoformat())
    for owner in db.scalars(select(Owner).order_by(Owner.id)).all():
        s.owners += 1
        try:
            _process_owner(db, owner, today, s)
        except Exception as exc:  # one owner's failure must not stop the others
            db.rollback()
            log.exception("Daily job failed for owner %s", owner.id)
            s.errors.append(f"owner {owner.id}: {exc.__class__.__name__}")
    return asdict(s)
