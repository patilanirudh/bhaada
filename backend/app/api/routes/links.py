"""Registration link endpoints (owner side)."""
from fastapi import APIRouter

from app.api.deps import Scope
from app.db.models import RegistrationLink
from app.schemas import LinkIn, LinkOut
from app.services import registration as svc
from app.services.audit import audit

router = APIRouter(prefix="/api/links", tags=["registration links"])


@router.get("", response_model=list[LinkOut])
def list_links(scope: Scope):
    links = scope.all(RegistrationLink, order_by=RegistrationLink.created_at.desc())
    return [svc.link_out(lk, scope.owner.name) for lk in links]


@router.post("", response_model=LinkOut, status_code=201)
def create_link(body: LinkIn, scope: Scope):
    return svc.link_out(svc.create_link(scope, body), scope.owner.name)


@router.post("/{link_id}/deactivate", response_model=LinkOut)
def deactivate_link(link_id: int, scope: Scope):
    link = scope.get_or_404(RegistrationLink, link_id, "Link")
    link.is_active = False
    audit(scope.db, scope.owner_id, "update", "registration_link", link.id, {"is_active": False})
    scope.db.commit()
    return svc.link_out(link, scope.owner.name)


@router.delete("/{link_id}", status_code=204)
def delete_link(link_id: int, scope: Scope):
    link = scope.get_or_404(RegistrationLink, link_id, "Link")
    audit(scope.db, scope.owner_id, "delete", "registration_link", link.id)
    scope.db.delete(link)
    scope.db.commit()
