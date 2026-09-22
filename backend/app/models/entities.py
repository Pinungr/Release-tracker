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

    ``LOCKED`` is accepted for compatibility but the UI lock is derived from
    date-based booking rules and administrator-controlled manual slot freezes,
    not stored on the booking.
    Statuses after ``CANCELLED`` are reserved for future validation workflows
    and are deliberately not surfaced in the UI yet.
    """

    BOOKED = "BOOKED"
    LOCKED = "LOCKED"
    IN_PROGRESS = "IN_PROGRESS"
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
    BookingStatus.IN_PROGRESS.value,
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
    DocumentCategory.IMPLEMENTATION_PLAN.value: "Implementation Document",
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
    # Optional tenant-specific quota. NULL means use the global default from
    # application_settings.weekly_booking_limit.
    weekly_booking_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    # The single protected owner account. Administrators manage tenant users
    # only; promoting, demoting, deactivating or resetting the password of an
    # ADMIN is reserved for the owner, and the owner account itself can never
    # be targeted through the admin API. There is no endpoint that grants this
    # flag, so it cannot be escalated into.
    is_owner: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0"), nullable=False
    )
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Incremented whenever the password is changed/reset. JWTs carry the
    # version that was current when they were issued, so older tokens remain
    # invalid even after an application restart.
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
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

    # Legacy database column name ``jira_change`` stores the Jira number.
    # The API/UI expose it as ``jira_number`` so it cannot be confused with
    # the separate Change No. that RM users add after assignment.
    jira_number: Mapped[str | None] = mapped_column("jira_change", String(64), nullable=True)
    jira_task: Mapped[str | None] = mapped_column(String(64), nullable=True)  # legacy, no longer exposed
    jira_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    change_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    work_started_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    work_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

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

    # Required on every change record. ``business_justification`` below is a
    # separate, emergency-only field and is not a substitute for this one.
    justification: Mapped[str] = mapped_column(Text, server_default="", nullable=False)
    impacted_region: Mapped[str] = mapped_column(
        String(160), server_default="", nullable=False
    )

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
    cancelled_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    attachments: Mapped[list["BookingAttachment"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan", lazy="selectin"
    )
    audit_events: Mapped[list["BookingAudit"]] = relationship(
        back_populates="booking", order_by="BookingAudit.id.desc()", passive_deletes=True
    )
    assignments: Mapped[list["BookingAssignment"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan", lazy="selectin"
    )


class BookingAssignment(Base):
    __tablename__ = "booking_assignments"
    __table_args__ = (
        UniqueConstraint("booking_id", "user_id", name="uq_booking_assignment_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("deployment_bookings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assigned_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    booking: Mapped[DeploymentBooking] = relationship(back_populates="assignments")
    user: Mapped[User] = relationship(foreign_keys=[user_id])
    assigned_by: Mapped[User | None] = relationship(foreign_keys=[assigned_by_user_id])


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


class SlotFreeze(Base):
    """Administrator-controlled lock for one normal deployment slot on one date."""

    __tablename__ = "slot_freezes"
    __table_args__ = (
        UniqueConstraint("freeze_date", "slot_number", name="uq_slot_freeze_date_number"),
        Index("ix_slot_freeze_date", "freeze_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    freeze_date: Mapped[date] = mapped_column(Date, nullable=False)
    slot_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class DailySlotCapacity(Base):
    """How many normal deployment slots one specific date carries.

    The administrator configures a default count in ``application_settings``
    (``regular_slots_per_day``) that applies to every deployment date. A row
    here exists only for dates where an administrator has added or removed
    slots; deleting the row restores that date to the default.

    Emergency changes are governed separately and are never affected by this.
    """

    __tablename__ = "daily_slot_capacity"

    id: Mapped[int] = mapped_column(primary_key=True)
    capacity_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    slot_count: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ApplicationSetting(Base):
    __tablename__ = "application_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class BookingAudit(Base):
    __tablename__ = "booking_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int | None] = mapped_column(
        ForeignKey("deployment_bookings.id", ondelete="SET NULL"), nullable=True, index=True
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
