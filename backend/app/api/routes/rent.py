"""Rent ledger and payment endpoints. Business rules live in ``app.services.ledger``."""
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Query
from pydantic import BaseModel, Field

from app.api.deps import Scope
from app.core.errors import NotFound
from app.db.models import Payment, RentEntry, Tenant
from app.integrations.storage import get_storage
from app.schemas import PaymentIn, RentEntryOut
from app.services import ledger as svc
from app.services.excel import autosave_excel

router = APIRouter(prefix="/api/rent", tags=["rent"])


class EntryUpdate(BaseModel):
    amount_due: int = Field(ge=0, le=100_000_000)


@router.get("/entries", response_model=list[RentEntryOut])
def list_entries(scope: Scope, month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
                 status_: str | None = Query(None, alias="status"), tenant_id: int | None = None,
                 property_id: int | None = None):
    stmt = scope.select(RentEntry).join(Tenant, Tenant.id == RentEntry.tenant_id)
    if month:
        stmt = stmt.where(RentEntry.month == month)
    if status_:
        stmt = stmt.where(RentEntry.status == status_)
    if tenant_id:
        stmt = stmt.where(RentEntry.tenant_id == tenant_id)
    if property_id:
        stmt = stmt.where(Tenant.property_id == property_id)
    entries = scope.db.scalars(stmt.order_by(RentEntry.due_date.desc(), Tenant.full_name)).all()
    return [svc.entry_out(e) for e in entries]


@router.post("/generate")
def generate_entries(scope: Scope, bg: BackgroundTasks):
    created = svc.generate_entries(scope)
    if created:
        bg.add_task(autosave_excel, scope.owner_id)
    return {"created": created}


@router.patch("/entries/{entry_id}", response_model=RentEntryOut)
def update_entry(entry_id: int, body: EntryUpdate, scope: Scope, bg: BackgroundTasks):
    e = svc.set_amount_due(scope, scope.get_or_404(RentEntry, entry_id, "Rent entry"), body.amount_due)
    bg.add_task(autosave_excel, scope.owner_id)
    return svc.entry_out(e)


@router.post("/entries/{entry_id}/payments", response_model=RentEntryOut, status_code=201)
def add_payment(entry_id: int, body: PaymentIn, scope: Scope, bg: BackgroundTasks):
    e = svc.record_payment(scope, scope.get_or_404(RentEntry, entry_id, "Rent entry"), body)
    bg.add_task(autosave_excel, scope.owner_id)
    return svc.entry_out(e)


@router.delete("/payments/{payment_id}", response_model=RentEntryOut)
def delete_payment(payment_id: int, scope: Scope, bg: BackgroundTasks):
    e = svc.delete_payment(scope, scope.get_or_404(Payment, payment_id, "Payment"))
    bg.add_task(autosave_excel, scope.owner_id)
    return svc.entry_out(e)


@router.get("/payments/{payment_id}/receipt-url")
def receipt_url(payment_id: int, scope: Scope):
    p = scope.get_or_404(Payment, payment_id, "Payment")
    if not p.receipt_pdf_path:
        raise NotFound("No receipt")
    return {"url": get_storage().signed_url(p.receipt_pdf_path), "expires_in": 300}


@router.get("/payments")
def list_payments(scope: Scope, from_: date | None = Query(None, alias="from"), to: date | None = None,
                  limit: int = Query(200, ge=1, le=1000)):
    stmt = scope.select(Payment).order_by(Payment.paid_on.desc(), Payment.id.desc()).limit(limit)
    if from_:
        stmt = stmt.where(Payment.paid_on >= from_)
    if to:
        stmt = stmt.where(Payment.paid_on <= to)
    out = []
    for p in scope.db.scalars(stmt):
        e, t = p.rent_entry, p.rent_entry.tenant
        out.append({**svc.payment_out(p).model_dump(), "month": e.month, "tenant_id": t.id,
                    "tenant_name": t.full_name, "unit_name": t.unit.name if t.unit else None,
                    "property_name": t.property.name if t.property else None, "entry_status": e.status})
    return out
