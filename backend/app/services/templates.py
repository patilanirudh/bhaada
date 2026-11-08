"""Editable message templates (WhatsApp + email body text), with English and Hindi defaults."""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import MessageTemplate, Owner

PLACEHOLDERS = ["{name}", "{amount}", "{month}", "{unit}", "{due_date}", "{upi_id}", "{owner_name}"]

KINDS = {
    "RENT_REMINDER": "Rent reminder (before / on due date)",
    "RENT_OVERDUE": "Overdue rent reminder",
    "INCREMENT_NOTICE": "Yearly rent increase notice (extra: {old_rent}, {new_rent}, {effective_date})",
    "WELCOME": "Welcome message on approval",
}

DEFAULTS: dict[str, dict[str, str]] = {
    "RENT_REMINDER": {
        "en": "Hi {name}, your rent of {amount} for {unit} ({month}) is due on {due_date}. "
              "Pay via UPI: {upi_id}. Please ignore if already paid. – {owner_name}",
        "hi": "नमस्ते {name}, {unit} का {month} का किराया {amount} दिनांक {due_date} को देय है। "
              "UPI से भुगतान करें: {upi_id}। अगर भुगतान कर दिया है तो कृपया इसे नज़रअंदाज़ करें। – {owner_name}",
    },
    "RENT_OVERDUE": {
        "en": "Hi {name}, your rent of {amount} for {unit} ({month}) was due on {due_date} and is still pending. "
              "Please pay via UPI: {upi_id} at the earliest. Ignore if already paid. – {owner_name}",
        "hi": "नमस्ते {name}, {unit} का {month} का किराया {amount} दिनांक {due_date} को देय था और अभी बाकी है। "
              "कृपया जल्द से जल्द UPI से भुगतान करें: {upi_id}। अगर भुगतान कर दिया है तो नज़रअंदाज़ करें। – {owner_name}",
    },
    "INCREMENT_NOTICE": {
        "en": "Hi {name}, as per your rental agreement for {unit}, the monthly rent will change from "
              "{old_rent} to {new_rent} from {effective_date}. – {owner_name}",
        "hi": "नमस्ते {name}, {unit} के किराया समझौते के अनुसार मासिक किराया {effective_date} से "
              "{old_rent} से बढ़कर {new_rent} हो जाएगा। – {owner_name}",
    },
    "WELCOME": {
        "en": "Hi {name}, welcome to {unit}! Your registration is approved. Monthly rent is {amount}, due on "
              "day {due_date} of every month. Pay via UPI: {upi_id}. – {owner_name}",
        "hi": "नमस्ते {name}, {unit} में आपका स्वागत है! आपका पंजीकरण स्वीकृत हो गया है। मासिक किराया {amount} है, "
              "जो हर महीने की {due_date} तारीख को देय है। UPI: {upi_id}। – {owner_name}",
    },
}

_PH = re.compile(r"\{([a-z_]+)\}")


def render(template: str, values: dict) -> str:
    return _PH.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), template)


def get_template(db: Session, owner: Owner, kind: str, language: str | None = None) -> str:
    lang = language or owner.preferred_language or "en"
    custom = db.scalar(
        select(MessageTemplate).where(
            MessageTemplate.owner_id == owner.id, MessageTemplate.kind == kind, MessageTemplate.language == lang
        )
    )
    if custom:
        return custom.body
    return DEFAULTS[kind].get(lang) or DEFAULTS[kind]["en"]
