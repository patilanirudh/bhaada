"""Public (no login) tenant self-registration via a registration link."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select, update

from app.core.config import get_settings
from app.api.deps import DB
from app.db.models import Owner, RegistrationLink, Tenant, TenantStatus
from app.api.routes.links import link_problem
from app.core.security import encrypt, random_token
from app.services.audit import audit
from app.integrations.email import notify_owner
from app.integrations.storage import get_storage
from app.utils.ratelimit import limiter
from app.utils.sanitize import sanitize_html
from app.utils.validators import (
    ALLOWED_DOC_TYPES,
    ALLOWED_PHOTO_TYPES,
    normalize_id_number,
    normalize_phone,
    sniff_mime,
    validate_id,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/public", tags=["public"])
MAX_UPLOAD = 5 * 1024 * 1024


def _get_link(db, token: str) -> RegistrationLink:
    link = db.scalar(select(RegistrationLink).where(RegistrationLink.token == token))
    if not link:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This registration link is not valid.")
    problem = link_problem(link)
    if problem:
        raise HTTPException(status.HTTP_410_GONE, problem)
    return link


@router.get("/register/{token}")
def registration_info(token: str, db: DB):
    link = _get_link(db, token)
    owner = db.get(Owner, link.owner_id)
    return {
        "property_name": link.property.name,
        "property_address": link.property.address,
        "unit_name": link.unit.name if link.unit else None,
        "house_rules": sanitize_html(link.property.house_rules),
        "owner_name": owner.name if owner else "",
        "expires_at": link.expires_at,
    }


async def _read_upload(f: UploadFile, allowed: dict[str, str], label: str) -> tuple[bytes, str, str]:
    data = await f.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{label} must be 5 MB or smaller")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{label} is empty")
    mime = sniff_mime(data)
    if mime not in allowed:
        kinds = ", ".join(v.upper() for v in allowed.values())
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{label} must be a {kinds} file")
    return data, mime, allowed[mime]


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/register/{token}", status_code=201)
async def submit_registration(
    token: str,
    request: Request,
    db: DB,
    full_name: str = Form(..., min_length=2, max_length=150),
    phone: str = Form(...),
    email: str = Form(...),
    permanent_address: str = Form(..., min_length=5, max_length=1000),
    id_type: str = Form(...),
    id_number: str = Form(...),
    consent: bool = Form(False),
    rules_accepted: bool = Form(False),
    website: str = Form(""),  # honeypot: humans never fill this
    id_document: UploadFile = File(...),
    photo: UploadFile | None = File(None),
):
    s = get_settings()
    if not limiter.allow(f"register:{_client_ip(request)}", s.registration_rate_limit, 3600):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many submissions. Please try again later.")
    link = _get_link(db, token)

    if website.strip():
        # Bot: pretend success, store nothing.
        log.info("Honeypot triggered on registration link %s", link.id)
        return {"detail": "Registration submitted"}

    errors: dict[str, str] = {}
    norm_phone = normalize_phone(phone)
    if not norm_phone:
        errors["phone"] = "Enter a valid 10-digit mobile number"
    email = email.strip().lower()
    from email_validator import EmailNotValidError, validate_email

    try:
        email = validate_email(email, check_deliverability=False).normalized
    except EmailNotValidError:
        errors["email"] = "Enter a valid email address"
    id_type = id_type.strip().upper()
    if id_type not in ("AADHAAR", "PAN"):
        errors["id_type"] = "Choose Aadhaar or PAN"
    else:
        id_number = normalize_id_number(id_type, id_number)
        err = validate_id(id_type, id_number)
        if err:
            errors["id_number"] = err
    if not consent:
        errors["consent"] = "You must agree to share your details with the owner"
    if link.property.house_rules and not rules_accepted:
        errors["rules_accepted"] = "Please confirm you have read the house rules"
    if errors:
        first = next(iter(errors.values()))
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"message": first, "errors": errors})

    doc_bytes, doc_mime, doc_ext = await _read_upload(id_document, ALLOWED_DOC_TYPES, "ID document")
    photo_data = None
    if photo is not None and photo.filename:
        photo_data = await _read_upload(photo, ALLOWED_PHOTO_TYPES, "Photo")

    # Atomically consume one use of the link (guards against concurrent submissions).
    res = db.execute(
        update(RegistrationLink)
        .where(RegistrationLink.id == link.id, RegistrationLink.use_count < RegistrationLink.max_uses,
               RegistrationLink.is_active.is_(True))
        .values(use_count=RegistrationLink.use_count + 1)
    )
    if res.rowcount != 1:
        db.rollback()
        raise HTTPException(status.HTTP_410_GONE, "This registration link has already been used.")

    now = datetime.now(timezone.utc)
    tenant = Tenant(
        owner_id=link.owner_id, property_id=link.property_id, unit_id=link.unit_id,
        full_name=full_name.strip(), phone=norm_phone, email=email, permanent_address=permanent_address.strip(),
        id_type=id_type, id_number_encrypted=encrypt(id_number), id_last4=id_number[-4:],
        status=TenantStatus.PENDING_APPROVAL, consent_given_at=now,
        rules_accepted_at=now if rules_accepted else None, registration_link_id=link.id,
        due_day=5, increment_percent=5.0,
    )
    if link.unit:
        tenant.base_rent = tenant.current_rent = link.unit.default_rent
    db.add(tenant)
    db.flush()

    storage = get_storage()
    base = f"owners/{link.owner_id}/tenants/{tenant.id}"
    saved: list[str] = []
    try:
        tenant.id_document_path = storage.save(f"{base}/id-{random_token(8)}.{doc_ext}", doc_bytes, doc_mime)
        saved.append(tenant.id_document_path)
        if photo_data:
            tenant.photo_path = storage.save(f"{base}/photo-{random_token(8)}.{photo_data[2]}", photo_data[0],
                                             photo_data[1])
            saved.append(tenant.photo_path)
        audit(db, link.owner_id, "create", "tenant", tenant.id, {"source": "registration_link", "link_id": link.id})
        db.commit()
    except Exception:
        db.rollback()
        for p in saved:
            try:
                storage.delete(p)
            except Exception:
                pass
        log.exception("Registration save failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not save your registration. Try again.")

    owner = db.get(Owner, link.owner_id)
    if owner:
        where = link.property.name + (f" – {link.unit.name}" if link.unit else "")
        notify_owner(owner, f"New tenant registration: {tenant.full_name}",
                     f"Hi {owner.name},\n\n{tenant.full_name} ({tenant.phone}) has registered for {where}.\n"
                     f"Open Rent Manager to review the ID document and approve or reject.\n\n"
                     f"{s.frontend_url.rstrip('/')}/tenants/{tenant.id}")
    return {"detail": "Registration submitted. The owner will review and confirm."}
