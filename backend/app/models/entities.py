"""Database entities for the Production Deployment Scheduler."""
from __future__ import annotations

import enum
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class BookingStatus(str, enum.Enum):
    """Stored booking lifecycle states.

    ``LOCKED`` is accepted for compatibility but the UI lock is *derived* from
    the configurable freeze window, not stored, so it can never go stale.
    Statuses after ``CANCELLED`` are reserved for future validation workflows
    and are deliberately not surfaced in the UI yet.
    """

    BOOKED = "BOOKED"
    LOCKED = "LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    VALIDATION_PENDING = "VALIDATION_PENDING"
    SUCCESSFUL = "SUCCESSFUL"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


#: Statuses that still occupy a slot.
ACTIVE_STATUSES = (
    BookingStatus.BOOKED.value,
    BookingStatus.LOCKED.value,
    BookingStatus.COMPLETED.value,
    BookingStatus.VALIDATION_PENDING.value,
    BookingStatus.SUCCESSFUL.value,
    BookingStatus.FAILED.value,
    BookingStatus.ROLLED_BACK.value,
)


class DocumentCategory(str, enum.Enum):
    TEST_RESULTS = "TEST_RESULTS"
    INVENTORY = "INVENTORY"
    IMPLEMENTATION_PLAN = "IMPLEMENTATION_PLAN"
    VALIDATION_PLAN = "VALIDATION_PLAN"
    DBA_SCRIPT = "DBA_SCRIPT"
    SUPPORTING_DOCUMENTS = "SUPPORTING_DOCUMENTS"


DOCUMENT_LABELS: dict[str, str] = {
    DocumentCategory.TEST_RESULTS.value: "Non-Production Test Result",
    DocumentCategory.INVENTORY.value: "Inventory File",
    DocumentCategory.IMPLEMENTATION_PLAN.value: "Implementation Plan",
    DocumentCategory.VALIDATION_PLAN.value: "Validation Plan",
    DocumentCategory.DBA_SCRIPT.value: "DBA Script",
    DocumentCategory.SUPPORTING_DOCUMENTS.value: "Supporting Documents",
}

#: Categories that accept more than one file.
MULTI_FILE_CATEGORIES = {DocumentCategory.SUPPORTING_DOCUMENTS.value}


class Technology(str, enum.Enum):
    DATABRICKS = "Databricks"
    AZDF = "AzDF"
    DATABASE = "Database"
    APPLICATION = "Application"
    INFRASTRUCTURE = "Infrastructure"
    OTHER = "Other"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    tenant_code: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(180), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="TENANT_USER", nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DeploymentSlotConfiguration(Base):
    """Normal deployment slot grid applied to every working day.

    Emergency changes are *not* slots: they live in a per-date admin queue
    (see ``DeploymentBooking.is_emergency``), so nothing here describes them.
    """

    __tablename__ = "slot_configurations"
    __table_args__ = (UniqueConstraint("slot_number", name="uq_slot_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    slot_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class DeploymentBooking(Base):
    __tablename__ = "deployment_bookings"
    __table_args__ = (
        # A normal slot holds at most one non-cancelled booking, enforced by
        # the database so two concurrent requests cannot both win. Emergency
        # changes are excluded from the index: a date may hold any number of
        # them, and they carry no slot_number at all.
        Index(
            "uq_active_slot_per_day",
            "deployment_date",
            "slot_number",
            unique=True,
            sqlite_where=text("status <> 'CANCELLED' AND is_emergency = 0"),
            postgresql_where=text("status <> 'CANCELLED' AND is_emergency = false"),
        ),
        Index("ix_booking_date", "deployment_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_reference: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    tenant_name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )

    deployment_date: Mapped[date] = mapped_column(Date, nullable=False)
    slot_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    jira_change: Mapped[str] = mapped_column(String(64), nullable=False)
    jira_task: Mapped[str | None] = mapped_column(String(64), nullable=True)
    jira_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    environment: Mapped[str] = mapped_column(String(32), default="PROD", nullable=False)
    technology: Mapped[str] = mapped_column(String(32), nullable=False)

    requester_name: Mapped[str] = mapped_column(String(120), nullable=False)
    requester_email: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    requester_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)

    verifier_name: Mapped[str] = mapped_column(String(120), nullable=False)
    verifier_email: Mapped[str] = mapped_column(String(180), nullable=False)

    git_repository: Mapped[str] = mapped_column(String(500), nullable=False)
    implementation_summary: Mapped[str] = mapped_column(Text, nullable=False)
    deployment_description: Mapped[str] = mapped_column(Text, nullable=False)
    additional_comments: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(32), default=BookingStatus.BOOKED.value, nullable=False)

    is_emergency: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    emergency_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    emergency_approval_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    emergency_approver: Mapped[str | None] = mapped_column(String(120), nullable=True)
    business_justification: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    attachments: Mapped[list["BookingAttachment"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan", lazy="selectin"
    )
    audit_events: Mapped[list["BookingAudit"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan", order_by="BookingAudit.id.desc()"
    )


class BookingAttachment(Base):
    __tablename__ = "booking_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("deployment_bookings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    uploaded_by: Mapped[str | None] = mapped_column(String(180), nullable=True)

    booking: Mapped[DeploymentBooking] = relationship(back_populates="attachments")


class Holiday(Base):
    __tablename__ = "holidays"

    id: Mapped[int] = mapped_column(primary_key=True)
    holiday_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_full_day: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_emergency: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DailySlotOverride(Base):
    """Per-date override of the default slot grid."""

    __tablename__ = "daily_slot_overrides"

    id: Mapped[int] = mapped_column(primary_key=True)
    override_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    regular_slots: Mapped[int | None] = mapped_column(Integer, nullable=True)
    emergency_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ApplicationSetting(Base):
    __tablename__ = "application_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class BookingAudit(Base):
    __tablename__ = "booking_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int | None] = mapped_column(
        ForeignKey("deployment_bookings.id", ondelete="CASCADE"), nullable=True, index=True
    )
    booking_reference: Mapped[str | None] = mapped_column(String(32), nullable=True)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)  # USER | ADMIN | SYSTEM
    requester_email: Mapped[str | None] = mapped_column(String(180), nullable=True)
    admin_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    old_values: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_values: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    booking: Mapped[DeploymentBooking | None] = relationship(back_populates="audit_events")
