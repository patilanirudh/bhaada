"""Excel use cases backed by the database: build the owner's export, auto-save it, import tenants."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session as database
from app.db.models import Owner, Property, RentEntry, RentHistory, Tenant, TenantStatus, Unit
from app.documents.excel import XLSX_MIME, write_sheet
from app.integrations.storage import get_storage
from app.services.rent import month_str, rebase_rent
from app.utils.formatting import today_ist
from app.utils.validators import mask_id

log = logging.getLogger(__name__)


log = logging.getLogger(__name__)


def build_export(db: Session, owner: Owner, today: date | None = None) -> bytes:
    today = today or today_ist()
    tenants = list(db.scalars(select(Tenant).where(Tenant.owner_id == owner.id).order_by(Tenant.full_name)))
    tmap = {t.id: t for t in tenants}
    wb = Workbook()

    write_sheet(wb, "Tenants",
           ["Name", "Phone", "Email", "Property", "Unit", "ID Type", "Masked ID", "Deposit", "Start Date",
            "End Date", "Base Rent", "Current Rent", "Increment %", "Due Day", "Status"],
           [[t.full_name, t.phone, t.email, t.property.name if t.property else None,
             t.unit.name if t.unit else None, t.id_type, mask_id(t.id_type, t.id_last4) if t.id_last4 else None,
             t.security_deposit, t.agreement_start_date, t.agreement_end_date, t.base_rent, t.current_rent,
             t.increment_percent, t.due_day, t.status] for t in tenants],
           money_cols=("Deposit", "Base Rent", "Current Rent"), date_cols=("Start Date", "End Date"), first=True)

    entries = list(db.scalars(select(RentEntry).where(RentEntry.owner_id == owner.id)
                              .order_by(RentEntry.month.desc(), RentEntry.tenant_id)))
    pay_rows = []
    for e in entries:
        name = tmap[e.tenant_id].full_name if e.tenant_id in tmap else ""
        if e.payments:
            for p in e.payments:
                pay_rows.append([name, e.month, e.amount_due, p.amount, p.paid_on, p.mode, p.reference,
                                 p.receipt_number, e.status])
        else:
            pay_rows.append([name, e.month, e.amount_due, 0, None, None, None, None, e.status])
    write_sheet(wb, "Payments",
           ["Tenant", "Month", "Amount Due", "Amount Paid", "Paid On", "Mode", "Reference", "Receipt No.", "Status"],
           pay_rows, money_cols=("Amount Due", "Amount Paid"), date_cols=("Paid On",))

    hist = list(db.scalars(select(RentHistory).where(RentHistory.owner_id == owner.id)
                           .order_by(RentHistory.effective_from.desc())))
    write_sheet(wb, "Rent History", ["Tenant", "Old Rent", "New Rent", "Effective From", "Reason"],
           [[tmap[h.tenant_id].full_name if h.tenant_id in tmap else "", h.old_rent, h.new_rent,
             h.effective_from, h.reason] for h in hist],
           money_cols=("Old Rent", "New Rent"), date_cols=("Effective From",))

    months = []
    m = date(today.year, today.month, 1)
    for _ in range(12):
        months.insert(0, month_str(m))
        m = (m - timedelta(days=1)).replace(day=1)
    agg = {mm: [0, 0] for mm in months}
    for e in entries:
        if e.month in agg:
            agg[e.month][0] += e.amount_due
            agg[e.month][1] += e.amount_paid
    write_sheet(wb, "Summary", ["Month", "Expected", "Collected", "Pending"],
           [[mm, a[0], a[1], a[0] - a[1]] for mm, a in agg.items()],
           money_cols=("Expected", "Collected", "Pending"))

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def autosave_path(owner_id: int) -> str:
    return f"owners/{owner_id}/rent-data.xlsx"


def autosave_excel(owner_id: int) -> None:
    """Regenerate the owner's saved Excel copy. Runs as a background task with its own session."""
    db = database.SessionLocal()
    try:
        owner = db.get(Owner, owner_id)
        if owner:
            get_storage().save(autosave_path(owner_id), build_export(db, owner), XLSX_MIME)
    except Exception:  # never break the request flow
        log.exception("Excel autosave failed for owner %s", owner_id)
    finally:
        db.close()




def import_rows(db: Session, owner: Owner, recs: list[dict]) -> int:
    from app.core.security import encrypt
    from app.services.rent import ensure_entries

    today = today_ist()
    props = {p.name.lower(): p for p in db.scalars(select(Property).where(Property.owner_id == owner.id))}
    count = 0
    for r in recs:
        if r["errors"]:
            continue
        prop = props.get(r["property"].lower())
        if not prop:
            prop = Property(owner_id=owner.id, name=r["property"])
            db.add(prop)
            db.flush()
            props[prop.name.lower()] = prop
        unit = db.scalar(select(Unit).where(Unit.property_id == prop.id, Unit.owner_id == owner.id,
                                            Unit.name == r["unit"]))
        if not unit:
            unit = Unit(owner_id=owner.id, property_id=prop.id, name=r["unit"], default_rent=r["base_rent"])
            db.add(unit)
            db.flush()
        t = Tenant(owner_id=owner.id, property_id=prop.id, unit_id=unit.id, full_name=r["full_name"],
                   phone=r["phone"], email=r["email"], permanent_address=r["permanent_address"],
                   security_deposit=r["security_deposit"], agreement_start_date=r["agreement_start_date"],
                   agreement_end_date=r["agreement_end_date"], increment_percent=r["increment_percent"],
                   due_day=r["due_day"], status=TenantStatus.ACTIVE)
        # Imported "Base Rent" is treated as the rent applicable today.
        rebase_rent(t, r["base_rent"], today)
        if r["id_number"]:
            t.id_type = r["id_type"]
            t.id_number_encrypted = encrypt(r["id_number"])
            t.id_last4 = r["id_number"][-4:]
        db.add(t)
        db.flush()
        ensure_entries(db, t, today)
        count += 1
    return count
