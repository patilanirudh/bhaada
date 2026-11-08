from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.utils.validators import normalize_phone


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth ----------
class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    phone: str | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        if v in (None, ""):
            return None
        p = normalize_phone(v)
        if not p:
            raise ValueError("Enter a valid mobile number")
        return p


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class OwnerOut(ORM):
    id: int
    name: str
    email: str
    phone: str | None
    upi_id: str | None
    gmail_address: str | None
    gmail_configured: bool = False
    preferred_language: str
    created_at: datetime
    default_house_rules: str | None = ""
    email_mode: str = "gmail"  # "service": app-wide email service (no owner Gmail needed)


class HouseRulesIn(BaseModel):
    house_rules: str = Field(max_length=20000)
    apply_to_all_properties: bool = False


class OwnerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = None
    upi_id: str | None = Field(default=None, max_length=100)
    preferred_language: Literal["en", "hi"] | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        if v in (None, ""):
            return v
        p = normalize_phone(v)
        if not p:
            raise ValueError("Enter a valid mobile number")
        return p

    @field_validator("upi_id")
    @classmethod
    def _upi(cls, v):
        if v in (None, ""):
            return v
        v = v.strip()
        import re

        if not re.fullmatch(r"[A-Za-z0-9.\-_]{2,256}@[A-Za-z]{2,64}", v):
            raise ValueError("UPI ID should look like name@bank")
        return v


class GmailIn(BaseModel):
    gmail_address: EmailStr
    app_password: str = Field(min_length=16, max_length=24)

    @field_validator("app_password")
    @classmethod
    def _pw(cls, v):
        v = v.replace(" ", "")
        if len(v) != 16:
            raise ValueError("A Gmail App Password has 16 letters (spaces are ignored)")
        return v


# ---------- properties ----------
class UnitIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    default_rent: int = Field(default=0, ge=0, le=10_000_000)


class UnitOut(ORM):
    id: int
    property_id: int
    name: str
    default_rent: int


class PropertyIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    address: str | None = None
    house_rules: str | None = None


class PropertyOut(ORM):
    id: int
    name: str
    address: str | None
    house_rules: str | None
    created_at: datetime
    units: list[UnitOut] = []


# ---------- registration links ----------
class LinkIn(BaseModel):
    property_id: int
    unit_id: int | None = None
    expires_in_days: int = Field(default=7, ge=1, le=90)
    max_uses: int = Field(default=1, ge=1, le=100)


class LinkOut(ORM):
    id: int
    property_id: int
    unit_id: int | None
    token: str
    expires_at: datetime
    max_uses: int
    use_count: int
    is_active: bool
    created_at: datetime
    url: str = ""
    property_name: str = ""
    unit_name: str | None = None
    whatsapp_url: str = ""
    usable: bool = True


# ---------- tenants ----------
TenantStatusT = Literal["PENDING_APPROVAL", "ACTIVE", "VACATED", "REJECTED"]


class TenantOut(BaseModel):
    id: int
    full_name: str
    phone: str
    email: str | None
    permanent_address: str | None
    id_type: str | None
    id_masked: str
    has_id_document: bool
    has_photo: bool
    property_id: int | None
    property_name: str | None
    unit_id: int | None
    unit_name: str | None
    security_deposit: int
    agreement_start_date: date | None
    agreement_end_date: date | None
    base_rent: int
    current_rent: int
    increment_percent: float
    due_day: int
    status: str
    consent_given_at: datetime | None
    created_at: datetime
    vacated_at: date | None
    settlement: dict | None = None
    has_settlement_pdf: bool = False
    last_reminded_on: date | None = None
    pending_amount: int = 0


class ApproveIn(BaseModel):
    base_rent: int = Field(gt=0, le=10_000_000)
    security_deposit: int = Field(default=0, ge=0, le=100_000_000)
    agreement_start_date: date
    agreement_end_date: date | None = None
    due_day: int = Field(default=5, ge=1, le=28)
    increment_percent: float = Field(default=5.0, ge=0, le=100)
    unit_id: int | None = None


class TenantUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    phone: str | None = None
    email: EmailStr | None = None
    permanent_address: str | None = None
    unit_id: int | None = None
    security_deposit: int | None = Field(default=None, ge=0)
    agreement_end_date: date | None = None
    increment_percent: float | None = Field(default=None, ge=0, le=100)
    due_day: int | None = Field(default=None, ge=1, le=28)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        if v is None:
            return v
        p = normalize_phone(v)
        if not p:
            raise ValueError("Enter a valid mobile number")
        return p


class TenantCreate(BaseModel):
    """Owner-entered tenant (already living there). ID is optional here."""
    full_name: str = Field(min_length=2, max_length=150)
    phone: str
    email: EmailStr | None = None
    permanent_address: str | None = None
    unit_id: int
    id_type: Literal["AADHAAR", "PAN"] | None = None
    id_number: str | None = None
    base_rent: int = Field(gt=0, le=10_000_000)
    security_deposit: int = Field(default=0, ge=0)
    agreement_start_date: date
    agreement_end_date: date | None = None
    due_day: int = Field(default=5, ge=1, le=28)
    increment_percent: float = Field(default=5.0, ge=0, le=100)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        p = normalize_phone(v)
        if not p:
            raise ValueError("Enter a valid mobile number")
        return p


class RentChangeIn(BaseModel):
    new_rent: int = Field(gt=0, le=10_000_000)


class RenewIn(BaseModel):
    new_end_date: date


class Deduction(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    amount: int = Field(ge=0)


class VacateIn(BaseModel):
    vacate_date: date
    deductions: list[Deduction] = []
    notes: str | None = Field(default=None, max_length=500)


# ---------- ledger ----------
class PaymentOut(ORM):
    id: int
    rent_entry_id: int
    amount: int
    paid_on: date
    mode: str
    reference: str | None
    receipt_number: str | None
    has_receipt: bool = False


class RentEntryOut(BaseModel):
    id: int
    tenant_id: int
    tenant_name: str
    unit_name: str | None
    property_name: str | None
    month: str
    amount_due: int
    amount_paid: int
    status: str
    due_date: date
    payments: list[PaymentOut] = []


class PaymentIn(BaseModel):
    amount: int = Field(gt=0, le=100_000_000)
    paid_on: date
    mode: Literal["UPI", "CASH", "BANK", "OTHER"]
    reference: str | None = Field(default=None, max_length=120)
    send_receipt: bool = True


class RentHistoryOut(ORM):
    id: int
    tenant_id: int
    old_rent: int
    new_rent: int
    effective_from: date
    reason: str


class ReminderLogOut(ORM):
    id: int
    tenant_id: int
    type: str
    channel: str
    ref: str | None
    sent_at: datetime
    status: str
    error: str | None


# ---------- templates / reminders ----------
class TemplateOut(BaseModel):
    kind: str
    language: str
    body: str
    is_custom: bool


class TemplateIn(BaseModel):
    kind: str
    language: Literal["en", "hi"]
    body: str = Field(min_length=5, max_length=2000)


class WhatsAppLogIn(BaseModel):
    tenant_id: int
    type: Literal["DUE_SOON", "DUE_TODAY", "OVERDUE", "INCREMENT_NOTICE", "WELCOME",
                  "AGREEMENT_EXPIRY"]
    ref: str | None = None
