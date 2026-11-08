from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from sqlalchemy import or_, select

from app.deps import Scope
from app.models import (
    Payment,
    Property,
    ReminderLog,
    RentEntry,
    RentHistory,
    RentStatus,
    Tenant,
    TenantStatus,
    Unit,
)
from app.schemas import (
    ApproveIn,
    PaymentOut,
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
from app.security import encrypt, random_token
from app.services.audit import audit
from app.services.excel import autosave_excel
from app.services.pdf import settlement_pdf
from app.services.rent import create_entry, ensure_entries, first_month, rebase_rent, rent_on
from app.services.storage import get_storage
from app.services.tenants import send_welcome, tenants_out
from app.utils.formatting import fmt_date, month_label, today_ist
from app.utils.validators import normalize_id_number, validate_id

router = APIRouter(prefix="/api/tenants", tags=["tenants"])


def _out(scope: Scope, t: Tenant) -> TenantOut:
    return tenants_out(scope.db, [t])[0]


def _unit_for(scope: Scope, unit_id: int) -> Unit:
    return scope.get_or_404(Unit, unit_id, "Unit")


@router.get("", response_model=list[TenantOut])
def list_tenants(scope: Scope, status_: str | None = Query(None, alias="status"), property_id: int | None = None,
                 q: str | None = None):
    stmt = scope.select(Tenant)
    if status_:
        stmt = stmt.where(Tenant.status == status_)
    if property_id:
        stmt = stmt.where(Tenant.property_id == property_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Tenant.full_name.ilike(like), Tenant.phone.ilike(like), Tenant.email.ilike(like)))
    tenants = list(scope.db.scalars(stmt.order_by(Tenant.created_at.desc())))
    return tenants_out(scope.db, tenants)


@router.post("", response_model=TenantOut, status_code=201)
def create_tenant(body: TenantCreate, scope: Scope, bg: BackgroundTasks):
    unit = _unit_for(scope, body.unit_id)
    t = Tenant(owner_id=scope.owner_id, property_id=unit.property_id, unit_id=unit.id,
               full_name=body.full_name.strip(), phone=body.phone, email=body.email,
               permanent_address=body.permanent_address, security_deposit=body.security_deposit,
               agreement_start_date=body.agreement_start_date, agreement_end_date=body.agreement_end_date,
               due_day=body.due_day, increment_percent=body.increment_percent, status=TenantStatus.ACTIVE)
    if body.id_number:
        if not body.id_type:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose the ID type")
        num = normalize_id_number(body.id_type, body.id_number)
        err = validate_id(body.id_type, num)
        if err:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, err)
        t.id_type, t.id_number_encrypted, t.id_last4 = body.id_type, encrypt(num), num[-4:]
    today = today_ist()
    # base_rent is the rent as of the agreement start; the formula derives today's rent.
    t.base_rent = body.base_rent
    t.rent_base_date = body.agreement_start_date
    t.current_rent = rent_on(t, today)
    scope.db.add(t)
    scope.db.flush()
    create_entry(scope.db, t, first_month(t, today), today)
    ensure_entries(scope.db, t, today)
    audit(scope.db, scope.owner_id, "create", "tenant", t.id, {"source": "owner"})
    scope.db.commit()
    bg.add_task(autosave_excel, scope.owner_id)
    return _out(scope, t)


@router.get("/{tenant_id}", response_model=TenantOut)
def get_tenant(tenant_id: int, scope: Scope):
    return _out(scope, scope.get_or_404(Tenant, tenant_id, "Tenant"))


@router.patch("/{tenant_id}", response_model=TenantOut)
def update_tenant(tenant_id: int, body: TenantUpdate, scope: Scope, bg: BackgroundTasks):
    t = scope.get_or_404(Tenant, tenant_id, "Tenant")
    data = body.model_dump(exclude_unset=True)
    if "unit_id" in data and data["unit_id"] is not None:
        unit = _unit_for(scope, data["unit_id"])
        t.property_id = unit.property_id
    if "increment_percent" in data and data["increment_percent"] != t.increment_percent:
        rebase_rent(t, t.current_rent or t.base_rent, today_ist())
    for k, v in data.items():
        setattr(t, k, v)
    audit(scope.db, scope.owner_id, "update", "tenant", t.id, {"fields": list(data)})
    scope.db.commit()
    bg.add_task(autosave_excel, scope.owner_id)
    return _out(scope, t)


@router.delete("/{tenant_id}", status_code=204)
def delete_tenant(tenant_id: int, scope: Scope, bg: BackgroundTasks):
    t = scope.get_or_404(Tenant, tenant_id, "Tenant")
    if t.status == TenantStatus.ACTIVE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vacate the tenant before deleting")
    _delete_documents(t)
    audit(scope.db, scope.owner_id, "delete", "tenant", t.id, {"name": t.full_name})
    scope.db.delete(t)
    scope.db.commit()
    bg.add_task(autosave_excel, scope.owner_id)


@router.post("/{tenant_id}/approve", response_model=TenantOut)
def approve(tenant_id: int, body: ApproveIn, scope: Scope, bg: BackgroundTasks):
    t = scope.get_or_404(Tenant, tenant_id, "Tenant")
    if t.status != TenantStatus.PENDING_APPROVAL:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only pending tenants can be approved")
    if body.unit_id is not None:
        unit = _unit_for(scope, body.unit_id)
        t.unit_id, t.property_id = unit.id, unit.property_id
    if not t.unit_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose the unit for this tenant")
    if body.agreement_end_date and body.agreement_end_date <= body.agreement_start_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Agreement end date must be after the start date")
    today = today_ist()
    t.base_rent = body.base_rent
    t.security_deposit = body.security_deposit
    t.agreement_start_date = body.agreement_start_date
    t.agreement_end_date = body.agreement_end_date
    t.rent_base_date = body.agreement_start_date
    t.due_day = body.due_day
    t.increment_percent = body.increment_percent
    t.status = TenantStatus.ACTIVE
    t.current_rent = rent_on(t, today)
    scope.db.flush()
    create_entry(scope.db, t, first_month(t, today), today)
    ensure_entries(scope.db, t, today)
    audit(scope.db, scope.owner_id, "approve", "tenant", t.id)
    scope.db.commit()
    scope.db.refresh(t)
    send_welcome(scope.db, scope.owner, t)
    scope.db.commit()
    bg.add_task(autosave_excel, scope.owner_id)
    return _out(scope, t)


@router.post("/{tenant_id}/reject", response_model=TenantOut)
def reject(tenant_id: int, scope: Scope, bg: BackgroundTasks):
    t = scope.get_or_404(Tenant, tenant_id, "Tenant")
    if t.status != TenantStatus.PENDING_APPROVAL:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only pending tenants can be rejected")
    t.status = TenantStatus.REJECTED
    # A rejected applicant's ID documents are not needed: delete them right away.
    _delete_documents(t)
    audit(scope.db, scope.owner_id, "reject", "tenant", t.id)
    scope.db.commit()
    bg.add_task(autosave_excel, scope.owner_id)
    return _out(scope, t)


def _signed(path: str | None) -> dict:
    if not path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No file uploaded")
    return {"url": get_storage().signed_url(path), "expires_in": 300}


@router.get("/{tenant_id}/document-url")
def document_url(tenant_id: int, scope: Scope):
    t = scope.get_or_404(Tenant, tenant_id, "Tenant")
    audit(scope.db, scope.owner_id, "view", "id_document", t.id)
    scope.db.commit()
    return _signed(t.id_document_path)


@router.get("/{tenant_id}/photo-url")
def photo_url(tenant_id: int, scope: Scope):
    return _signed(scope.get_or_404(Tenant, tenant_id, "Tenant").photo_path)


def _delete_documents(t: Tenant) -> bool:
    storage = get_storage()
    deleted = False
    for attr in ("id_document_path", "photo_path"):
        path = getattr(t, attr)
        if path:
            storage.delete(path)
            setattr(t, attr, None)
            deleted = True
    if deleted:
        t.id_documents_deleted_at = datetime.now(timezone.utc)
    return deleted


@router.delete("/{tenant_id}/documents", response_model=TenantOut)
def delete_documents(tenant_id: int, scope: Scope):
    t = scope.get_or_404(Tenant, tenant_id, "Tenant")
    if t.status == TenantStatus.ACTIVE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ID documents can be deleted after the tenant vacates")
    _delete_documents(t)
    audit(scope.db, scope.owner_id, "delete", "id_document", t.id)
    scope.db.commit()
    return _out(scope, t)


@router.post("/{tenant_id}/rent-change", response_model=TenantOut)
def change_rent(tenant_id: int, body: RentChangeIn, scope: Scope, bg: BackgroundTasks):
    t = scope.get_or_404(Tenant, tenant_id, "Tenant")
    if t.status != TenantStatus.ACTIVE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tenant is not active")
    today = today_ist()
    old = t.current_rent
    rebase_rent(t, body.new_rent, today)
    scope.db.add(RentHistory(owner_id=t.owner_id, tenant_id=t.id, old_rent=old, new_rent=body.new_rent,
                             effective_from=today, reason="MANUAL"))
    audit(scope.db, scope.owner_id, "update", "tenant", t.id, {"rent": [old, body.new_rent]})
    scope.db.commit()
    bg.add_task(autosave_excel, scope.owner_id)
    return _out(scope, t)


@router.post("/{tenant_id}/renew", response_model=TenantOut)
def renew(tenant_id: int, body: RenewIn, scope: Scope, bg: BackgroundTasks):
    t = scope.get_or_404(Tenant, tenant_id, "Tenant")
    if t.agreement_start_date and body.new_end_date <= t.agreement_start_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New end date must be after the agreement start")
    old = t.agreement_end_date
    t.agreement_end_date = body.new_end_date
    audit(scope.db, scope.owner_id, "update", "tenant", t.id,
          {"renewed": [old.isoformat() if old else None, body.new_end_date.isoformat()]})
    scope.db.commit()
    bg.add_task(autosave_excel, scope.owner_id)
    return _out(scope, t)


def _settlement(scope: Scope, t: Tenant, body: VacateIn) -> dict:
    unpaid = scope.all(RentEntry, RentEntry.tenant_id == t.id, RentEntry.status != RentStatus.PAID,
                       RentEntry.month <= body.vacate_date.strftime("%Y-%m"), order_by=RentEntry.month)
    pending_months = [{"month": e.month, "label": month_label(e.month), "amount": e.amount_due - e.amount_paid}
                      for e in unpaid if e.amount_due > e.amount_paid]
    pending = sum(p["amount"] for p in pending_months)
    deductions = [d.model_dump() for d in body.deductions]
    total_ded = sum(d["amount"] for d in deductions)
    return {
        "vacate_date": body.vacate_date.isoformat(), "deposit": t.security_deposit,
        "pending_rent": pending, "pending_months": pending_months, "deductions": deductions,
        "total_deductions": total_ded, "refund": t.security_deposit - pending - total_ded,
        "notes": body.notes,
    }


@router.post("/{tenant_id}/settlement-preview")
def settlement_preview(tenant_id: int, body: VacateIn, scope: Scope):
    t = scope.get_or_404(Tenant, tenant_id, "Tenant")
    return _settlement(scope, t, body)


@router.post("/{tenant_id}/vacate", response_model=TenantOut)
def vacate(tenant_id: int, body: VacateIn, scope: Scope, bg: BackgroundTasks):
    t = scope.get_or_404(Tenant, tenant_id, "Tenant")
    if t.status != TenantStatus.ACTIVE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only active tenants can be vacated")
    st = _settlement(scope, t, body)
    # Remove future months that were pre-generated beyond the vacate month.
    for e in scope.all(RentEntry, RentEntry.tenant_id == t.id, RentEntry.month > body.vacate_date.strftime("%Y-%m"),
                       RentEntry.amount_paid == 0):
        scope.db.delete(e)
    pdf = settlement_pdf(
        owner_name=scope.owner.name, tenant_name=t.full_name,
        property_name=t.property.name if t.property else "", unit_name=t.unit.name if t.unit else "",
        agreement_start=fmt_date(t.agreement_start_date), vacate_date=fmt_date(body.vacate_date),
        deposit=st["deposit"], pending_rent=st["pending_rent"],
        pending_months=[(p["label"], p["amount"]) for p in st["pending_months"]],
        deductions=[(d["label"], d["amount"]) for d in st["deductions"]], refund=st["refund"],
        notes=body.notes, generated_on=fmt_date(today_ist()),
    )
    path = get_storage().save(f"owners/{t.owner_id}/tenants/{t.id}/settlement-{random_token(6)}.pdf", pdf,
                              "application/pdf")
    t.status = TenantStatus.VACATED
    t.vacated_at = body.vacate_date
    t.settlement = st
    t.settlement_pdf_path = path
    audit(scope.db, scope.owner_id, "update", "tenant", t.id, {"vacated": body.vacate_date.isoformat(),
                                                               "refund": st["refund"]})
    scope.db.commit()
    bg.add_task(autosave_excel, scope.owner_id)
    return _out(scope, t)


@router.get("/{tenant_id}/settlement-url")
def settlement_url(tenant_id: int, scope: Scope):
    return _signed(scope.get_or_404(Tenant, tenant_id, "Tenant").settlement_pdf_path)


@router.get("/{tenant_id}/ledger", response_model=list[RentEntryOut])
def tenant_ledger(tenant_id: int, scope: Scope):
    t = scope.get_or_404(Tenant, tenant_id, "Tenant")
    from app.routers.rent import entry_out

    return [entry_out(e) for e in scope.all(RentEntry, RentEntry.tenant_id == t.id, order_by=RentEntry.month.desc())]


@router.get("/{tenant_id}/rent-history", response_model=list[RentHistoryOut])
def tenant_history(tenant_id: int, scope: Scope):
    t = scope.get_or_404(Tenant, tenant_id, "Tenant")
    return scope.all(RentHistory, RentHistory.tenant_id == t.id, order_by=RentHistory.effective_from.desc())


@router.get("/{tenant_id}/reminders", response_model=list[ReminderLogOut])
def tenant_reminders(tenant_id: int, scope: Scope):
    t = scope.get_or_404(Tenant, tenant_id, "Tenant")
    return scope.all(ReminderLog, ReminderLog.tenant_id == t.id, order_by=ReminderLog.sent_at.desc())
