"""SQLAlchemy models.

Every table holding owner data carries an ``owner_id`` column so that every
query can be scoped to the logged-in owner (see ``app.deps.OwnerScope``).
Money is stored as whole rupees (Integer).
"""
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TenantStatus:
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    VACATED = "VACATED"
    REJECTED = "REJECTED"
    ALL = (PENDING_APPROVAL, ACTIVE, VACATED, REJECTED)


class RentStatus:
    DUE = "DUE"
    PARTIAL = "PARTIAL"
    PAID = "PAID"
    OVERDUE = "OVERDUE"


class ReminderType:
    DUE_SOON = "DUE_SOON"
    DUE_TODAY = "DUE_TODAY"
    OVERDUE = "OVERDUE"
    INCREMENT_NOTICE = "INCREMENT_NOTICE"
    WELCOME = "WELCOME"
    AGREEMENT_EXPIRY = "AGREEMENT_EXPIRY"
    RECEIPT = "RECEIPT"


class Channel:
    EMAIL = "EMAIL"
    WHATSAPP_MANUAL = "WHATSAPP_MANUAL"


class Owner(Base):
    __tablename__ = "owners"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20))
    upi_id: Mapped[str | None] = mapped_column(String(100))
    gmail_address: Mapped[str | None] = mapped_column(String(255))
    gmail_app_password_encrypted: Mapped[str | None] = mapped_column(Text)
    preferred_language: Mapped[str] = mapped_column(String(2), default="en")
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    address: Mapped[str | None] = mapped_column(Text)
    house_rules: Mapped[str | None] = mapped_column(Text)  # sanitized HTML
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    units: Mapped[list["Unit"]] = relationship(
        back_populates="property", cascade="all, delete-orphan", order_by="Unit.name"
    )


class Unit(Base):
    __tablename__ = "units"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    default_rent: Mapped[int] = mapped_column(Integer, default=0)

    property: Mapped[Property] = relationship(back_populates="units")


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[int | None] = mapped_column(ForeignKey("properties.id", ondelete="SET NULL"))
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"))
    full_name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str] = mapped_column(String(20))  # E.164
    email: Mapped[str | None] = mapped_column(String(255))
    permanent_address: Mapped[str | None] = mapped_column(Text)
    id_type: Mapped[str | None] = mapped_column(String(10))  # AADHAAR | PAN
    id_number_encrypted: Mapped[str | None] = mapped_column(Text)
    id_last4: Mapped[str | None] = mapped_column(String(4))
    id_document_path: Mapped[str | None] = mapped_column(String(500))
    photo_path: Mapped[str | None] = mapped_column(String(500))
    security_deposit: Mapped[int] = mapped_column(Integer, default=0)
    agreement_start_date: Mapped[date | None] = mapped_column(Date)
    agreement_end_date: Mapped[date | None] = mapped_column(Date)
    base_rent: Mapped[int] = mapped_column(Integer, default=0)
    # Rent formula anchor: rent = base_rent * (1+pct)^(completed years since rent_base_date).
    # Equals agreement_start_date unless the owner manually changed the rent.
    rent_base_date: Mapped[date | None] = mapped_column(Date)
    current_rent: Mapped[int] = mapped_column(Integer, default=0)
    increment_percent: Mapped[float] = mapped_column(Float, default=5.0)
    due_day: Mapped[int] = mapped_column(Integer, default=5)
    status: Mapped[str] = mapped_column(String(20), default=TenantStatus.PENDING_APPROVAL, index=True)
    consent_given_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rules_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registration_link_id: Mapped[int | None] = mapped_column(
        ForeignKey("registration_links.id", ondelete="SET NULL")
    )
    settlement: Mapped[dict | None] = mapped_column(JSON)
    settlement_pdf_path: Mapped[str | None] = mapped_column(String(500))
    id_documents_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    vacated_at: Mapped[date | None] = mapped_column(Date)

    property: Mapped[Property | None] = relationship()
    unit: Mapped[Unit | None] = relationship()


class RegistrationLink(Base):
    __tablename__ = "registration_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"))
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"))
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    property: Mapped[Property] = relationship()
    unit: Mapped[Unit | None] = relationship()


class RentEntry(Base):
    __tablename__ = "rent_entries"
    __table_args__ = (UniqueConstraint("tenant_id", "month", name="uq_rent_entry_tenant_month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    month: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    amount_due: Mapped[int] = mapped_column(Integer)
    amount_paid: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10), default=RentStatus.DUE)
    due_date: Mapped[date] = mapped_column(Date, index=True)

    tenant: Mapped[Tenant] = relationship()
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="rent_entry", cascade="all, delete-orphan", order_by="Payment.paid_on"
    )


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    rent_entry_id: Mapped[int] = mapped_column(ForeignKey("rent_entries.id", ondelete="CASCADE"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    paid_on: Mapped[date] = mapped_column(Date)
    mode: Mapped[str] = mapped_column(String(10))  # UPI | CASH | BANK | OTHER
    reference: Mapped[str | None] = mapped_column(String(120))
    receipt_number: Mapped[str | None] = mapped_column(String(40))
    receipt_pdf_path: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    rent_entry: Mapped[RentEntry] = relationship(back_populates="payments")


class RentHistory(Base):
    __tablename__ = "rent_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    old_rent: Mapped[int] = mapped_column(Integer)
    new_rent: Mapped[int] = mapped_column(Integer)
    effective_from: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(20))  # YEARLY_INCREMENT | MANUAL
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReminderLog(Base):
    __tablename__ = "reminder_logs"
    __table_args__ = (Index("ix_reminder_dedupe", "tenant_id", "type", "channel", "ref"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(20))
    channel: Mapped[str] = mapped_column(String(20))
    # Dedupe key: e.g. rent entry month, anniversary date
    ref: Mapped[str | None] = mapped_column(String(60))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_on: Mapped[date | None] = mapped_column(Date)  # IST date of the attempt
    status: Mapped[str] = mapped_column(String(10))  # SENT | FAILED | SKIPPED
    error: Mapped[str | None] = mapped_column(String(500))


class MessageTemplate(Base):
    __tablename__ = "message_templates"
    __table_args__ = (UniqueConstraint("owner_id", "kind", "language", name="uq_template_owner_kind_lang"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    language: Mapped[str] = mapped_column(String(2))
    body: Mapped[str] = mapped_column(Text)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(30))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
