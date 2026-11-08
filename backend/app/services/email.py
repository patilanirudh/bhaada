"""Email sending via Gmail SMTP (each owner's own Gmail + App Password).

Backends:
- smtp:    real Gmail SMTP (default)
- console: log the email instead of sending (local dev without Gmail)
- memory:  keep emails in ``OUTBOX`` (tests)
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage

from app.config import get_settings
from app.models import Owner
from app.security import decrypt

log = logging.getLogger(__name__)


@dataclass
class Attachment:
    filename: str
    data: bytes
    mime: str = "application/pdf"


@dataclass
class SentEmail:
    sender: str
    to: str
    subject: str
    text: str
    html: str | None = None
    attachments: list[Attachment] = field(default_factory=list)


OUTBOX: list[SentEmail] = []
# Tests can put addresses here to simulate SMTP failures.
FAIL_ADDRESSES: set[str] = set()


class EmailError(Exception):
    pass


@dataclass
class SmtpCredentials:
    address: str
    app_password: str
    display_name: str


def owner_credentials(owner: Owner) -> SmtpCredentials | None:
    if not owner.gmail_address or not owner.gmail_app_password_encrypted:
        return None
    pw = decrypt(owner.gmail_app_password_encrypted)
    if not pw:
        return None
    return SmtpCredentials(owner.gmail_address, pw, owner.name)


def system_credentials() -> SmtpCredentials | None:
    s = get_settings()
    if not s.system_gmail_address or not s.system_gmail_app_password:
        return None
    return SmtpCredentials(s.system_gmail_address, s.system_gmail_app_password, s.app_name)


def send_email(creds: SmtpCredentials | None, to: str, subject: str, text: str, html: str | None = None,
               attachments: list[Attachment] | None = None, reply_to: str | None = None) -> None:
    """Send an email. Raises EmailError on failure (callers decide whether to log/retry)."""
    s = get_settings()
    attachments = attachments or []
    backend = s.email_backend
    if creds is None and backend == "smtp":
        raise EmailError("Gmail is not configured")
    sender = creds.address if creds else "no-reply@localhost"

    if backend in ("memory", "console"):
        if to in FAIL_ADDRESSES:
            raise EmailError("Simulated SMTP failure")
        msg = SentEmail(sender, to, subject, text, html, attachments)
        if backend == "memory":
            OUTBOX.append(msg)
        else:
            log.info("EMAIL (console) from=%s to=%s subject=%s\n%s", sender, to, subject, text)
        return

    msg = EmailMessage()
    msg["From"] = f"{creds.display_name} <{creds.address}>"
    msg["To"] = to
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    for a in attachments:
        maintype, subtype = a.mime.split("/", 1)
        msg.add_attachment(a.data, maintype=maintype, subtype=subtype, filename=a.filename)
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=ctx, timeout=20) as smtp:
            smtp.login(creds.address, creds.app_password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise EmailError("Gmail rejected the login. Check the Gmail address and App Password.") from e
    except (smtplib.SMTPException, OSError) as e:
        raise EmailError(f"Could not send email: {e.__class__.__name__}") from e


def send_owner_email(owner: Owner, to: str, subject: str, text: str, html: str | None = None,
                     attachments: list[Attachment] | None = None) -> None:
    """Send from the owner's Gmail; falls back to the system Gmail (shown with the owner's name,
    replies go to the owner) when the owner has not connected their own Gmail yet."""
    creds = owner_credentials(owner)
    if creds is None:
        sys = system_credentials()
        creds = SmtpCredentials(sys.address, sys.app_password, owner.name) if sys else None
    send_email(creds, to, subject, text, html, attachments, reply_to=owner.email)


def notify_owner(owner: Owner, subject: str, text: str) -> str | None:
    """Notify the owner: from their own Gmail to themselves, else via the system account.

    Never raises. Returns None on success, or the error message.
    """
    creds = owner_credentials(owner) or system_credentials()
    try:
        send_email(creds, owner.email, subject, text)
        return None
    except EmailError as e:
        log.warning("Owner notification failed for owner %s: %s", owner.id, e)
        return str(e)
