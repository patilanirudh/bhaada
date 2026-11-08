from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, status

from app.core.config import get_settings
from app.api.deps import Scope
from app.db.models import Property, RegistrationLink, Unit
from app.schemas import LinkIn, LinkOut
from app.services.audit import audit
from app.integrations.whatsapp import wa_link
from app.core.security import random_token

router = APIRouter(prefix="/api/links", tags=["registration links"])


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def link_problem(link: RegistrationLink, now: datetime | None = None) -> str | None:
    """Why a link cannot be used, or None if it is usable."""
    now = now or datetime.now(timezone.utc)
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
    where = f"{out.property_name}" + (f" ({out.unit_name})" if out.unit_name else "")
    msg = (f"Hello! Please register as a tenant for {where} using this secure link: {out.url}\n"
           f"Keep your Aadhaar or PAN ready. – {owner_name}")
    out.whatsapp_url = wa_link(None, msg)
    out.usable = link_problem(link) is None
    return out


@router.get("", response_model=list[LinkOut])
def list_links(scope: Scope):
    links = scope.all(RegistrationLink, order_by=RegistrationLink.created_at.desc())
    return [link_out(lk, scope.owner.name) for lk in links]


@router.post("", response_model=LinkOut, status_code=201)
def create_link(body: LinkIn, scope: Scope):
    prop = scope.get_or_404(Property, body.property_id, "Property")
    if body.unit_id is not None:
        unit = scope.get_or_404(Unit, body.unit_id, "Unit")
        if unit.property_id != prop.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unit does not belong to this property")
    link = RegistrationLink(
        owner_id=scope.owner_id, property_id=prop.id, unit_id=body.unit_id, token=random_token(32),
        expires_at=datetime.now(timezone.utc) + timedelta(days=body.expires_in_days), max_uses=body.max_uses,
    )
    scope.db.add(link)
    scope.db.flush()
    audit(scope.db, scope.owner_id, "create", "registration_link", link.id, {"property_id": prop.id})
    scope.db.commit()
    scope.db.refresh(link)
    return link_out(link, scope.owner.name)


@router.post("/{link_id}/deactivate", response_model=LinkOut)
def deactivate_link(link_id: int, scope: Scope):
    link = scope.get_or_404(RegistrationLink, link_id, "Link")
    link.is_active = False
    audit(scope.db, scope.owner_id, "update", "registration_link", link.id, {"is_active": False})
    scope.db.commit()
    return link_out(link, scope.owner.name)


@router.delete("/{link_id}", status_code=204)
def delete_link(link_id: int, scope: Scope):
    link = scope.get_or_404(RegistrationLink, link_id, "Link")
    audit(scope.db, scope.owner_id, "delete", "registration_link", link.id)
    scope.db.delete(link)
    scope.db.commit()
