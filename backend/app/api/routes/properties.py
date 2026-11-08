from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.core.defaults import DEFAULT_HOUSE_RULES
from app.api.deps import Scope
from app.db.models import Property, Tenant, TenantStatus, Unit
from app.schemas import PropertyIn, PropertyOut, UnitIn, UnitOut
from app.services.audit import audit
from app.utils.sanitize import sanitize_html

router = APIRouter(prefix="/api/properties", tags=["properties"])


@router.get("", response_model=list[PropertyOut])
def list_properties(scope: Scope):
    return scope.all(Property, order_by=Property.name)


@router.post("", response_model=PropertyOut, status_code=201)
def create_property(body: PropertyIn, scope: Scope):
    rules = body.house_rules if body.house_rules is not None else (
        scope.owner.default_house_rules or DEFAULT_HOUSE_RULES)
    p = Property(owner_id=scope.owner_id, name=body.name.strip(), address=body.address,
                 house_rules=sanitize_html(rules))
    scope.db.add(p)
    scope.db.flush()
    audit(scope.db, scope.owner_id, "create", "property", p.id, {"name": p.name})
    scope.db.commit()
    scope.db.refresh(p)
    return p


@router.get("/{property_id}", response_model=PropertyOut)
def get_property(property_id: int, scope: Scope):
    return scope.get_or_404(Property, property_id, "Property")


@router.put("/{property_id}", response_model=PropertyOut)
def update_property(property_id: int, body: PropertyIn, scope: Scope):
    p = scope.get_or_404(Property, property_id, "Property")
    p.name = body.name.strip()
    p.address = body.address
    p.house_rules = sanitize_html(body.house_rules)
    audit(scope.db, scope.owner_id, "update", "property", p.id)
    scope.db.commit()
    scope.db.refresh(p)
    return p


@router.delete("/{property_id}", status_code=204)
def delete_property(property_id: int, scope: Scope):
    p = scope.get_or_404(Property, property_id, "Property")
    active = scope.db.scalar(
        select(func.count()).select_from(Tenant).where(
            Tenant.owner_id == scope.owner_id, Tenant.property_id == p.id,
            Tenant.status.in_([TenantStatus.ACTIVE, TenantStatus.PENDING_APPROVAL]),
        )
    )
    if active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vacate or reject the tenants of this property first")
    audit(scope.db, scope.owner_id, "delete", "property", p.id, {"name": p.name})
    scope.db.delete(p)
    scope.db.commit()


@router.post("/{property_id}/units", response_model=UnitOut, status_code=201)
def create_unit(property_id: int, body: UnitIn, scope: Scope):
    p = scope.get_or_404(Property, property_id, "Property")
    u = Unit(owner_id=scope.owner_id, property_id=p.id, name=body.name.strip(), default_rent=body.default_rent)
    scope.db.add(u)
    scope.db.flush()
    audit(scope.db, scope.owner_id, "create", "unit", u.id, {"name": u.name})
    scope.db.commit()
    return u


@router.put("/units/{unit_id}", response_model=UnitOut)
def update_unit(unit_id: int, body: UnitIn, scope: Scope):
    u = scope.get_or_404(Unit, unit_id, "Unit")
    u.name = body.name.strip()
    u.default_rent = body.default_rent
    audit(scope.db, scope.owner_id, "update", "unit", u.id)
    scope.db.commit()
    return u


@router.delete("/units/{unit_id}", status_code=204)
def delete_unit(unit_id: int, scope: Scope):
    u = scope.get_or_404(Unit, unit_id, "Unit")
    occupied = scope.db.scalar(
        select(func.count()).select_from(Tenant).where(
            Tenant.owner_id == scope.owner_id, Tenant.unit_id == u.id, Tenant.status == TenantStatus.ACTIVE
        )
    )
    if occupied:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This unit has an active tenant")
    audit(scope.db, scope.owner_id, "delete", "unit", u.id, {"name": u.name})
    scope.db.delete(u)
    scope.db.commit()
