"""Tenant endpoints. HTTP mapping only; business rules live in ``app.services.tenants``."""
from fastapi import APIRouter, BackgroundTasks, Query

from app.api.deps import Scope
from app.core.errors import NotFound
from app.db.models import ReminderLog, RentEntry, RentHistory, Tenant
from app.integrations.storage import get_storage
from app.schemas import (
    ApproveIn,
    ReminderLogOut,
    RenewIn,
    RentChangeIn,
    RentEntryOut,
    RentHistoryOut,
    TenantCreate,
    TenantOut,
    TenantUpdate,
    VacateIn,
)
from app.services import tenants as svc
from app.services.audit import audit
from app.services.excel import autosave_excel
from app.services.ledger import entry_out

router = APIRouter(prefix="/api/tenants", tags=["tenants"])


def _out(scope: Scope, t: Tenant) -> TenantOut:
    return svc.tenants_out(scope.db, [t])[0]


def _get(scope: Scope, tenant_id: int) -> Tenant:
    return scope.get_or_404(Tenant, tenant_id, "Tenant")


def _signed(path: str | None) -> dict:
    if not path:
        raise NotFound("No file uploaded")
    return {"url": get_storage().signed_url(path), "expires_in": 300}


@router.get("", response_model=list[TenantOut])
def list_tenants(scope: Scope, status_: str | None = Query(None, alias="status"), property_id: int | None = None,
                 q: str | None = Query(None, max_length=100)):
    from sqlalchemy import or_

    stmt = scope.select(Tenant)
    if status_:
        stmt = stmt.where(Tenant.status == status_)
    if property_id:
        stmt = stmt.where(Tenant.property_id == property_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Tenant.full_name.ilike(like), Tenant.phone.ilike(like), Tenant.email.ilike(like)))
    return svc.tenants_out(scope.db, list(scope.db.scalars(stmt.order_by(Tenant.created_at.desc()))))


@router.post("", response_model=TenantOut, status_code=201)
def create_tenant(body: TenantCreate, scope: Scope, bg: BackgroundTasks):
    t = svc.create_tenant(scope, body)
    bg.add_task(autosave_excel, scope.owner_id)
    return _out(scope, t)


@router.get("/{tenant_id}", response_model=TenantOut)
def get_tenant(tenant_id: int, scope: Scope):
    return _out(scope, _get(scope, tenant_id))


@router.patch("/{tenant_id}", response_model=TenantOut)
def update_tenant(tenant_id: int, body: TenantUpdate, scope: Scope, bg: BackgroundTasks):
    t = svc.update_tenant(scope, _get(scope, tenant_id), body.model_dump(exclude_unset=True))
    bg.add_task(autosave_excel, scope.owner_id)
    return _out(scope, t)


@router.delete("/{tenant_id}", status_code=204)
def delete_tenant(tenant_id: int, scope: Scope, bg: BackgroundTasks):
    svc.delete_tenant(scope, _get(scope, tenant_id))
    bg.add_task(autosave_excel, scope.owner_id)


@router.post("/{tenant_id}/approve", response_model=TenantOut)
def approve(tenant_id: int, body: ApproveIn, scope: Scope, bg: BackgroundTasks):
    t = svc.approve(scope, _get(scope, tenant_id), body)
    bg.add_task(autosave_excel, scope.owner_id)
    return _out(scope, t)


@router.post("/{tenant_id}/reject", response_model=TenantOut)
def reject(tenant_id: int, scope: Scope, bg: BackgroundTasks):
    t = svc.reject(scope, _get(scope, tenant_id))
    bg.add_task(autosave_excel, scope.owner_id)
    return _out(scope, t)


@router.get("/{tenant_id}/document-url")
def document_url(tenant_id: int, scope: Scope):
    t = _get(scope, tenant_id)
    audit(scope.db, scope.owner_id, "view", "id_document", t.id)  # every ID view is audited
    scope.db.commit()
    return _signed(t.id_document_path)


@router.get("/{tenant_id}/photo-url")
def photo_url(tenant_id: int, scope: Scope):
    return _signed(_get(scope, tenant_id).photo_path)


@router.delete("/{tenant_id}/documents", response_model=TenantOut)
def delete_documents(tenant_id: int, scope: Scope):
    return _out(scope, svc.remove_documents(scope, _get(scope, tenant_id)))


@router.post("/{tenant_id}/erase", response_model=TenantOut)
def erase_personal_data(tenant_id: int, scope: Scope, bg: BackgroundTasks):
    t = svc.erase_personal_data(scope, _get(scope, tenant_id))
    bg.add_task(autosave_excel, scope.owner_id)
    return _out(scope, t)


@router.post("/{tenant_id}/rent-change", response_model=TenantOut)
def change_rent(tenant_id: int, body: RentChangeIn, scope: Scope, bg: BackgroundTasks):
    t = svc.change_rent(scope, _get(scope, tenant_id), body.new_rent)
    bg.add_task(autosave_excel, scope.owner_id)
    return _out(scope, t)


@router.post("/{tenant_id}/renew", response_model=TenantOut)
def renew(tenant_id: int, body: RenewIn, scope: Scope, bg: BackgroundTasks):
    t = svc.renew(scope, _get(scope, tenant_id), body.new_end_date)
    bg.add_task(autosave_excel, scope.owner_id)
    return _out(scope, t)


@router.post("/{tenant_id}/settlement-preview")
def settlement_preview(tenant_id: int, body: VacateIn, scope: Scope):
    return svc.settlement(scope, _get(scope, tenant_id), body)


@router.post("/{tenant_id}/vacate", response_model=TenantOut)
def vacate(tenant_id: int, body: VacateIn, scope: Scope, bg: BackgroundTasks):
    t = svc.vacate(scope, _get(scope, tenant_id), body)
    bg.add_task(autosave_excel, scope.owner_id)
    return _out(scope, t)


@router.get("/{tenant_id}/settlement-url")
def settlement_url(tenant_id: int, scope: Scope):
    return _signed(_get(scope, tenant_id).settlement_pdf_path)


@router.get("/{tenant_id}/ledger", response_model=list[RentEntryOut])
def tenant_ledger(tenant_id: int, scope: Scope):
    t = _get(scope, tenant_id)
    return [entry_out(e) for e in scope.all(RentEntry, RentEntry.tenant_id == t.id, order_by=RentEntry.month.desc())]


@router.get("/{tenant_id}/rent-history", response_model=list[RentHistoryOut])
def tenant_history(tenant_id: int, scope: Scope):
    t = _get(scope, tenant_id)
    return scope.all(RentHistory, RentHistory.tenant_id == t.id, order_by=RentHistory.effective_from.desc())


@router.get("/{tenant_id}/reminders", response_model=list[ReminderLogOut])
def tenant_reminders(tenant_id: int, scope: Scope):
    t = _get(scope, tenant_id)
    return scope.all(ReminderLog, ReminderLog.tenant_id == t.id, order_by=ReminderLog.sent_at.desc())
