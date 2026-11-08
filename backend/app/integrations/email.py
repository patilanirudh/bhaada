"""Email sending via Gmail SMTP (each owner's own Gmail + App Password).

Backends:
- smtp:    real Gmail SMTP (default)
- console: log the email instead of sending (local dev without Gmail)
- memory:  keep emails in ``OUTBOX`` (tests)
"""
from __future__ import annotations

import base64
import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from html import escape as html_escape

import httpx

from app.core.config import get_settings
from app.core.security import decrypt
from app.db.models import Owner

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


BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def _send_brevo(creds: SmtpCredentials | None, to: str, subject: str, text: str, html: str | None,
                attachments: list[Attachment], reply_to: str | None) -> None:
    """Send through Brevo's HTTPS API (port 443).

    Used where outbound SMTP is blocked (e.g. Render's free plan blocks 25/465/587).
    The sender address must be verified in Brevo; the display name is the owner's name.
    """
    s = get_settings()
    sender_email = s.email_sender_address or s.system_gmail_address
    if not s.brevo_api_key or not sender_email:
        raise EmailError("Email service is not configured (BREVO_API_KEY / sender address)")
    payload: dict = {
        "sender": {"email": sender_email, "name": (creds.display_name if creds else s.app_name)[:70]},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": text,
        "htmlContent": html or "<pre style=\"font-family:inherit;white-space:pre-wrap\">"
                               f"{html_escape(text)}</pre>",
    }
    if reply_to:
        payload["replyTo"] = {"email": reply_to}
    if attachments:
        payload["attachment"] = [{"name": a.filename, "content": base64.b64encode(a.data).decode()}
                                 for a in attachments]
    try:
        r = httpx.post(BREVO_URL, json=payload, timeout=20,
                       headers={"api-key": s.brevo_api_key, "accept": "application/json"})
    except httpx.HTTPError as e:
        raise EmailError(f"Could not reach the email service: {e.__class__.__name__}") from e
    if r.status_code >= 300:
        try:
            detail = r.json().get("message", "")
        except ValueError:
            detail = ""
        raise EmailError(f"Email service rejected the message ({r.status_code}) {detail}".strip())


def send_email(creds: SmtpCredentials | None, to: str, subject: str, text: str, html: str | None = None,
               attachments: list[Attachment] | None = None, reply_to: str | None = None) -> None:
    """Send an email. Raises EmailError on failure (callers decide whether to log/retry)."""
    s = get_settings()
    attachments = attachments or []
    backend = s.email_backend
    if backend == "brevo":
        _send_brevo(creds, to, subject, text, html, attachments, reply_to)
        return
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
