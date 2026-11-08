"""Excel file handling (no database): export formatting, import template, parsing and validation."""
from __future__ import annotations

from datetime import date, datetime
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.utils.validators import mask_id, normalize_id_number, normalize_phone, validate_id

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


INR_FMT = '[>=10000000]"₹"##\\,##\\,##\\,##0;[>=100000]"₹"##\\,##\\,##0;"₹"#,##0'


DATE_FMT = "DD-MMM-YYYY"


HEADER_FILL = PatternFill("solid", fgColor="E2E8F0")


def write_sheet(wb: Workbook, title: str, headers: list[str], rows: list[list], money_cols=(), date_cols=(),
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
            if isinstance(v, (date, datetime)):
                ln = 12
            elif isinstance(v, (int, float)):
                ln = len(f"{v:,}") + 2
            else:
                ln = len(str(v))
            width = max(width, ln)
        ws.column_dimensions[letter].width = min(max(10, width + 2), 50)
    return ws


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
    ws = write_sheet(wb, "Tenants", headers, [example], money_cols=("Base Rent", "Deposit"),
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
        def get(key, row=row):
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
