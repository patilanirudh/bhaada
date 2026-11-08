"""Excel export (database is the source of truth), auto-saved copy, blank template and import."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session as database
from app.db.models import Owner, Payment, Property, RentEntry, RentHistory, Tenant, TenantStatus, Unit
from app.services.rent import month_str, rebase_rent
from app.integrations.storage import get_storage
from app.utils.formatting import today_ist
from app.utils.validators import mask_id, normalize_id_number, normalize_phone, validate_id

log = logging.getLogger(__name__)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# Indian digit grouping (₹1,50,000) via conditional sections.
INR_FMT = '[>=10000000]"₹"##\\,##\\,##\\,##0;[>=100000]"₹"##\\,##\\,##0;"₹"#,##0'
DATE_FMT = "DD-MMM-YYYY"
HEADER_FILL = PatternFill("solid", fgColor="E2E8F0")


def _sheet(wb: Workbook, title: str, headers: list[str], rows: list[list], money_cols=(), date_cols=(),
           first: bool = False):
    ws = wb.active if first else wb.create_sheet()
    ws.title = title
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = HEADER_FILL
        c.alignment = Alignment(vertical="center")
    for r in rows:
        ws.append(r)
    ws.freeze_panes = "A2"
    for idx, h in enumerate(headers, start=1):
        letter = get_column_letter(idx)
        for cell in ws[letter][1:]:
            if h in money_cols:
                cell.number_format = INR_FMT
            elif h in date_cols:
                cell.number_format = DATE_FMT
        width = len(str(h))
        for cell in ws[letter][1:]:
            v = cell.value
            if v is None:
                continue
            ln = 12 if isinstance(v, (date, datetime)) else len(f"{v:,}") + 2 if isinstance(v, (int, float)) else len(str(v))
            width = max(width, ln)
        ws.column_dimensions[letter].width = min(max(10, width + 2), 50)
    return ws


def build_export(db: Session, owner: Owner, today: date | None = None) -> bytes:
    today = today or today_ist()
    tenants = list(db.scalars(select(Tenant).where(Tenant.owner_id == owner.id).order_by(Tenant.full_name)))
    tmap = {t.id: t for t in tenants}
    wb = Workbook()

    _sheet(wb, "Tenants",
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
    _sheet(wb, "Payments",
           ["Tenant", "Month", "Amount Due", "Amount Paid", "Paid On", "Mode", "Reference", "Receipt No.", "Status"],
           pay_rows, money_cols=("Amount Due", "Amount Paid"), date_cols=("Paid On",))

    hist = list(db.scalars(select(RentHistory).where(RentHistory.owner_id == owner.id)
                           .order_by(RentHistory.effective_from.desc())))
    _sheet(wb, "Rent History", ["Tenant", "Old Rent", "New Rent", "Effective From", "Reason"],
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
    _sheet(wb, "Summary", ["Month", "Expected", "Collected", "Pending"],
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


# ---------- import ----------
IMPORT_FIELDS: dict[str, dict] = {
    "full_name": {"label": "Full Name", "required": True, "aliases": ["name", "tenant", "tenant name"]},
    "phone": {"label": "Phone", "required": True, "aliases": ["mobile", "phone number", "contact"]},
    "email": {"label": "Email", "required": False, "aliases": ["email id", "mail"]},
    "property": {"label": "Property", "required": True, "aliases": ["building", "property name"]},
    "unit": {"label": "Unit", "required": True, "aliases": ["flat", "room", "unit name", "flat no"]},
    "base_rent": {"label": "Base Rent", "required": True, "aliases": ["rent", "monthly rent", "current rent"]},
    "security_deposit": {"label": "Deposit", "required": False, "aliases": ["security deposit", "advance"]},
    "agreement_start_date": {"label": "Start Date", "required": True,
                             "aliases": ["agreement start", "start", "joining date", "move in"]},
    "agreement_end_date": {"label": "End Date", "required": False, "aliases": ["agreement end", "end"]},
    "due_day": {"label": "Due Day", "required": False, "aliases": ["due date", "rent due day"]},
    "increment_percent": {"label": "Increment %", "required": False, "aliases": ["increment", "hike %"]},
    "permanent_address": {"label": "Permanent Address", "required": False, "aliases": ["address"]},
    "id_type": {"label": "ID Type", "required": False, "aliases": []},
    "id_number": {"label": "ID Number", "required": False, "aliases": ["aadhaar", "pan", "id"]},
}


def build_template() -> bytes:
    wb = Workbook()
    headers = [f["label"] for f in IMPORT_FIELDS.values()]
    example = ["Ravi Kumar", "9876543210", "ravi@example.com", "Green Residency", "Flat 203", 15000, 30000,
               date(2025, 4, 1), date(2026, 3, 31), 5, 5, "12 MG Road, Pune", "PAN", "ABCDE1234F"]
    ws = _sheet(wb, "Tenants", headers, [example], money_cols=("Base Rent", "Deposit"),
                date_cols=("Start Date", "End Date"), first=True)
    ws.cell(row=2, column=1).font = Font(italic=True, color="64748B")
    info = wb.create_sheet("Instructions")
    for line in [
        "Fill one tenant per row in the 'Tenants' sheet. Delete the example row.",
        "Required: Full Name, Phone, Property, Unit, Base Rent, Start Date.",
        "Base Rent: the monthly rent the tenant pays today (future yearly increments start from it).",
        "Phone: 10-digit Indian mobile, or with +91.",
        "Dates: DD-MMM-YYYY (e.g. 01-Apr-2025) or a real Excel date.",
        "Due Day: 1 to 28 (default 5). Increment %: default 5.",
        "ID Type: AADHAAR or PAN (optional). ID numbers are encrypted; only the last 4 digits are shown.",
        "Missing properties and units are created automatically.",
    ]:
        info.append([line])
    info.column_dimensions["A"].width = 100
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _norm(s) -> str:
    return " ".join(str(s or "").strip().lower().replace("_", " ").split())


def read_sheet(data: bytes) -> tuple[list[str], list[list]]:
    wb = load_workbook(BytesIO(data), data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    rows = [r for r in rows if any(c not in (None, "") for c in r)]
    if not rows:
        return [], []
    headers = [str(h).strip() if h is not None else f"Column {i + 1}" for i, h in enumerate(rows[0])]
    return headers, rows[1:]


def suggest_mapping(headers: list[str]) -> dict[str, str | None]:
    normed = {_norm(h): h for h in headers}
    mapping: dict[str, str | None] = {}
    for key, f in IMPORT_FIELDS.items():
        found = None
        for cand in [f["label"], key, *f["aliases"]]:
            if _norm(cand) in normed:
                found = normed[_norm(cand)]
                break
        mapping[key] = found
    return mapping


def _parse_date(v) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%d %b %Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"'{s}' is not a valid date (use DD-MMM-YYYY)")


def _parse_int(v, default=None) -> int | None:
    if v in (None, ""):
        return default
    if isinstance(v, (int, float)):
        return int(round(v))
    s = str(v).replace("₹", "").replace(",", "").replace("Rs.", "").replace("Rs", "").strip()
    return int(round(float(s)))


def parse_rows(headers: list[str], rows: list[list], mapping: dict[str, str | None]) -> list[dict]:
    idx = {h: i for i, h in enumerate(headers)}
    out = []
    for n, row in enumerate(rows, start=2):
        def get(key):
            col = mapping.get(key)
            if not col or col not in idx or idx[col] >= len(row):
                return None
            v = row[idx[col]]
            return v.strip() if isinstance(v, str) else v

        errors: list[str] = []
        rec: dict = {"row": n}
        for key, f in IMPORT_FIELDS.items():
            if f["required"] and get(key) in (None, ""):
                errors.append(f"{f['label']} is required")
        rec["full_name"] = str(get("full_name") or "").strip()
        phone_raw = get("phone")
        phone = normalize_phone(str(phone_raw)) if phone_raw not in (None, "") else None
        if phone_raw not in (None, "") and not phone:
            errors.append("Phone is not a valid mobile number")
        rec["phone"] = phone
        rec["email"] = (str(get("email")).strip().lower() if get("email") else None)
        if rec["email"] and "@" not in rec["email"]:
            errors.append("Email is not valid")
        rec["property"] = str(get("property") or "").strip()
        rec["unit"] = str(get("unit") or "").strip()
        rec["permanent_address"] = get("permanent_address")
        try:
            rec["base_rent"] = _parse_int(get("base_rent"))
            if rec["base_rent"] is not None and rec["base_rent"] <= 0:
                errors.append("Base Rent must be more than 0")
            rec["security_deposit"] = _parse_int(get("security_deposit"), 0)
            rec["due_day"] = _parse_int(get("due_day"), 5)
            if not 1 <= rec["due_day"] <= 28:
                errors.append("Due Day must be between 1 and 28")
            inc = get("increment_percent")
            rec["increment_percent"] = float(str(inc).replace("%", "")) if inc not in (None, "") else 5.0
        except (TypeError, ValueError):
            errors.append("A number column has an invalid value")
        try:
            rec["agreement_start_date"] = _parse_date(get("agreement_start_date"))
            rec["agreement_end_date"] = _parse_date(get("agreement_end_date"))
        except ValueError as e:
            errors.append(str(e))
        id_type = str(get("id_type") or "").strip().upper() or None
        id_number = get("id_number")
        if id_number not in (None, ""):
            id_number = normalize_id_number(id_type or "", str(id_number))
            if not id_type:
                id_type = "AADHAAR" if id_number.isdigit() else "PAN"
            err = validate_id(id_type, id_number)
            if err:
                errors.append(err)
        rec["id_type"] = id_type if id_number else None
        rec["id_number"] = id_number or None
        rec["errors"] = errors
        out.append(rec)
    return out


def preview_dict(rec: dict) -> dict:
    """Safe-for-UI version of a parsed row (ID masked)."""
    d = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in rec.items() if k != "id_number"}
    d["id_masked"] = mask_id(rec.get("id_type"), rec["id_number"][-4:]) if rec.get("id_number") else None
    return d


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
