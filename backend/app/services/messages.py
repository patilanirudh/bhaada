"""Builds reminder/notice texts for tenants (shared by email and WhatsApp).

Never put ID numbers into any of these messages.
"""
from __future__ import annotations

from datetime import date
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.db.models import Owner, RentEntry, Tenant
from app.services.templates import get_template, render
from app.utils.formatting import fmt_date, fmt_short, inr, month_label


def unit_label(t: Tenant) -> str:
    if t.unit and t.property:
        return f"{t.unit.name}, {t.property.name}"
    if t.unit:
        return t.unit.name
    return t.property.name if t.property else "your flat"


def upi_link(owner: Owner, amount: int, month: str) -> str | None:
    if not owner.upi_id:
        return None
    tn = f"Rent {month_label(month)}"
    return (f"upi://pay?pa={quote(owner.upi_id, safe='@.')}&pn={quote(owner.name)}"
            f"&am={amount}&cu=INR&tn={quote(tn)}")


def first_name(full: str) -> str:
    return full.split()[0] if full else full


def rent_values(owner: Owner, tenant: Tenant, entry: RentEntry) -> dict:
    balance = entry.amount_due - entry.amount_paid
    return {
        "name": first_name(tenant.full_name),
        "amount": inr(balance),
        "month": month_label(entry.month),
        "unit": unit_label(tenant),
        "due_date": fmt_short(entry.due_date),
        "upi_id": owner.upi_id or "(ask owner)",
        "owner_name": owner.name,
    }


def rent_reminder_text(db: Session, owner: Owner, tenant: Tenant, entry: RentEntry, today: date) -> str:
    kind = "RENT_OVERDUE" if entry.due_date < today else "RENT_REMINDER"
    return render(get_template(db, owner, kind), rent_values(owner, tenant, entry))


def increment_text(db: Session, owner: Owner, tenant: Tenant, old: int, new: int, effective: date) -> str:
    values = {
        "name": first_name(tenant.full_name), "unit": unit_label(tenant), "owner_name": owner.name,
        "old_rent": inr(old), "new_rent": inr(new), "effective_date": fmt_date(effective),
        "amount": inr(new), "upi_id": owner.upi_id or "", "month": "", "due_date": "",
    }
    return render(get_template(db, owner, "INCREMENT_NOTICE"), values)


def welcome_text(db: Session, owner: Owner, tenant: Tenant) -> str:
    values = {
        "name": first_name(tenant.full_name), "unit": unit_label(tenant), "owner_name": owner.name,
        "amount": inr(tenant.current_rent), "due_date": str(tenant.due_day), "upi_id": owner.upi_id or "",
        "month": "",
    }
    return render(get_template(db, owner, "WELCOME"), values)
