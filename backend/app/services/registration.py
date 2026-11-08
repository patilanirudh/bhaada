"""Registration links and tenant self-registration use cases."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import BadRequest, Gone, NotFound, ServerError, ValidationFailed
from app.core.security import encrypt, random_token
from app.db.models import Owner, Property, RegistrationLink, Tenant, TenantStatus, Unit
from app.db.scope import OwnerScope
from app.integrations.email import notify_owner
from app.integrations.storage import get_storage
from app.integrations.whatsapp import wa_link
from app.schemas import LinkIn, LinkOut
from app.services.audit import audit
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
MAX_UPLOAD = 5 * 1024 * 1024


# ---------- links (owner side) ----------
def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def link_problem(link: RegistrationLink, now: datetime | None = None) -> str | None:
    """Why a link cannot be used, or None if it is usable."""
    now = now or datetime.now(UTC)
    if not link.is_active:
        return "This registration link has been turned off by the owner."
    if _aware(link.expires_at) <= now:
        return "This registration link has expired. Please ask the owner for a new one."
    if link.use_count >= link.max_uses:
        return "This registration link has already been used. Please ask the owner for a new one."
    return None


def link_out(link: RegistrationLink, owner_name: str) -> LinkOut:
    out = LinkOut.model_validate(link)
    out.url = f"{get_settings().frontend_url.rstrip('/')}/register/{link.token}"
    out.property_name = link.property.name if link.property else ""
    out.unit_name = link.unit.name if link.unit else None
    where = out.property_name + (f" ({out.unit_name})" if out.unit_name else "")
    out.whatsapp_url = wa_link(None, f"Hello! Please register as a tenant for {where} using this secure link: "
                                     f"{out.url}\nKeep your Aadhaar or PAN ready. - {owner_name}")
    out.usable = link_problem(link) is None
    return out


def create_link(scope: OwnerScope, body: LinkIn) -> RegistrationLink:
    prop = scope.get_or_404(Property, body.property_id, "Property")
    if body.unit_id is not None and scope.get_or_404(Unit, body.unit_id, "Unit").property_id != prop.id:
        raise BadRequest("Unit does not belong to this property")
    link = RegistrationLink(
        owner_id=scope.owner_id, property_id=prop.id, unit_id=body.unit_id, token=random_token(32),
        expires_at=datetime.now(UTC) + timedelta(days=body.expires_in_days), max_uses=body.max_uses,
    )
    scope.db.add(link)
    scope.db.flush()
    audit(scope.db, scope.owner_id, "create", "registration_link", link.id, {"property_id": prop.id})
    scope.db.commit()
    scope.db.refresh(link)
    return link


# ---------- public registration (tenant side) ----------
def get_usable_link(db: Session, token: str) -> RegistrationLink:
    link = db.scalar(select(RegistrationLink).where(RegistrationLink.token == token))
    if not link:
        raise NotFound("This registration link is not valid.")
    problem = link_problem(link)
    if problem:
        raise Gone(problem)
    return link


def public_info(db: Session, token: str) -> dict:
    link = get_usable_link(db, token)
    owner = db.get(Owner, link.owner_id)
    return {
        "property_name": link.property.name,
        "property_address": link.property.address,
        "unit_name": link.unit.name if link.unit else None,
        "house_rules": sanitize_html(link.property.house_rules),
        "owner_name": owner.name if owner else "",
        "expires_at": link.expires_at,
    }


@dataclass
class Upload:
    data: bytes
    label: str


@dataclass
class RegistrationForm:
    full_name: str
    phone: str
    email: str
    permanent_address: str
    id_type: str
    id_number: str
    consent: bool
    rules_accepted: bool
    id_document: Upload
    photo: Upload | None = None


def _check_file(up: Upload, allowed: dict[str, str]) -> tuple[str, str]:
    """Validate size and real file type (magic bytes). Returns (mime, extension)."""
    if len(up.data) > MAX_UPLOAD:
        raise BadRequest(f"{up.label} must be 5 MB or smaller")
    if not up.data:
        raise BadRequest(f"{up.label} is empty")
    mime = sniff_mime(up.data)
    if mime not in allowed:
        raise BadRequest(f"{up.label} must be a {', '.join(v.upper() for v in allowed.values())} file")
    return mime, allowed[mime]


def _validate(form: RegistrationForm, link: RegistrationLink) -> tuple[str, str, str, str]:
    errors: dict[str, str] = {}
    phone = normalize_phone(form.phone)
    if not phone:
        errors["phone"] = "Enter a valid 10-digit mobile number"
    email = form.email.strip().lower()
    try:
        email = validate_email(email, check_deliverability=False).normalized
    except EmailNotValidError:
        errors["email"] = "Enter a valid email address"
    id_type = form.id_type.strip().upper()
    id_number = ""
    if id_type not in ("AADHAAR", "PAN"):
        errors["id_type"] = "Choose Aadhaar or PAN"
    else:
        id_number = normalize_id_number(id_type, form.id_number)
        err = validate_id(id_type, id_number)
        if err:
            errors["id_number"] = err
    if not form.consent:
        errors["consent"] = "You must agree to share your details with the owner"
    if link.property.house_rules and not form.rules_accepted:
        errors["rules_accepted"] = "Please confirm you have read the house rules"
    if errors:
        raise ValidationFailed(next(iter(errors.values())), errors)
    return phone, email, id_type, id_number  # type: ignore[return-value]


def submit_registration(db: Session, token: str, form: RegistrationForm) -> Tenant:
    link = get_usable_link(db, token)
    phone, email, id_type, id_number = _validate(form, link)
    doc_mime, doc_ext = _check_file(form.id_document, ALLOWED_DOC_TYPES)
    photo_meta = _check_file(form.photo, ALLOWED_PHOTO_TYPES) if form.photo else None

    # Atomically consume one use of the link (guards against concurrent submissions).
    res = db.execute(
        update(RegistrationLink)
        .where(RegistrationLink.id == link.id, RegistrationLink.use_count < RegistrationLink.max_uses,
               RegistrationLink.is_active.is_(True))
        .values(use_count=RegistrationLink.use_count + 1)
    )
    if res.rowcount != 1:
        db.rollback()
        raise Gone("This registration link has already been used.")

    now = datetime.now(UTC)
    tenant = Tenant(
        owner_id=link.owner_id, property_id=link.property_id, unit_id=link.unit_id,
        full_name=form.full_name.strip(), phone=phone, email=email, permanent_address=form.permanent_address.strip(),
        id_type=id_type, id_number_encrypted=encrypt(id_number), id_last4=id_number[-4:],
        status=TenantStatus.PENDING_APPROVAL, consent_given_at=now,
        rules_accepted_at=now if form.rules_accepted else None, registration_link_id=link.id,
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
        tenant.id_document_path = storage.save(f"{base}/id-{random_token(8)}.{doc_ext}", form.id_document.data,
                                               doc_mime)
        saved.append(tenant.id_document_path)
        if form.photo and photo_meta:
            tenant.photo_path = storage.save(f"{base}/photo-{random_token(8)}.{photo_meta[1]}", form.photo.data,
                                             photo_meta[0])
            saved.append(tenant.photo_path)
        audit(db, link.owner_id, "create", "tenant", tenant.id, {"source": "registration_link", "link_id": link.id})
        db.commit()
    except Exception as exc:
        db.rollback()
        for p in saved:
            try:
                storage.delete(p)
            except Exception:  # best effort cleanup
                log.warning("Could not clean up an upload after a failed registration")
        log.exception("Registration save failed")
        raise ServerError("Could not save your registration. Please try again.") from exc

    owner = db.get(Owner, link.owner_id)
    if owner:
        where = link.property.name + (f" - {link.unit.name}" if link.unit else "")
        notify_owner(owner, f"New tenant registration: {tenant.full_name}",
                     f"Hi {owner.name},\n\n{tenant.full_name} ({tenant.phone}) has registered for {where}.\n"
                     "Open Rent Manager to review the ID document and approve or reject.\n\n"
                     f"{get_settings().frontend_url.rstrip('/')}/tenants/{tenant.id}")
    return tenant
