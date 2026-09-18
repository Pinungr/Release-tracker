"""Request/response schemas for bookings and owner verification."""
from __future__ import annotations

import re
from datetime import date, datetime, time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from ..models import DocumentCategory, Technology

PIN_PATTERN = re.compile(r"^\d{6}$")
_HTTP_URL = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)
_SCP_GIT = re.compile(r"^(git|ssh)://[^\s]+$|^[\w.-]+@[\w.-]+:[\w./~-]+$", re.IGNORECASE)

Pin = Annotated[str, Field(min_length=6, max_length=6)]
ShortText = Annotated[str, Field(min_length=1, max_length=120)]


def _validate_pin(value: str) -> str:
    if not PIN_PATTERN.match(value or ""):
        raise ValueError("Booking PIN must be exactly 6 digits.")
    return value


def _validate_repo(value: str) -> str:
    value = (value or "").strip()
    if not (_HTTP_URL.match(value) or _SCP_GIT.match(value)):
        raise ValueError("Enter a valid Git repository URL (https://…, ssh://… or git@host:path).")
    return value


def _validate_optional_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    if not _HTTP_URL.match(value):
        raise ValueError("Enter a valid http(s) URL.")
    return value


class BookingBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    tenant_name: ShortText
    jira_change: Annotated[str, Field(min_length=3, max_length=64)]
    jira_task: Annotated[str | None, Field(default=None, max_length=64)] = None
    jira_url: Annotated[str | None, Field(default=None, max_length=500)] = None
    environment: Annotated[str, Field(default="PROD", max_length=32)] = "PROD"
    technology: Technology
    requester_name: ShortText
    requester_email: EmailStr
    requester_phone: Annotated[str | None, Field(default=None, max_length=40)] = None
    verifier_name: ShortText
    verifier_email: EmailStr
    git_repository: Annotated[str, Field(max_length=500)]
    implementation_summary: Annotated[str, Field(min_length=10, max_length=4000)]
    deployment_description: Annotated[str, Field(min_length=10, max_length=4000)]
    additional_comments: Annotated[str | None, Field(default=None, max_length=4000)] = None

    # Emergency-only fields (validated against is_emergency in the service layer).
    emergency_reason: Annotated[str | None, Field(default=None, max_length=2000)] = None
    emergency_approval_reference: Annotated[str | None, Field(default=None, max_length=120)] = None
    emergency_approver: Annotated[str | None, Field(default=None, max_length=120)] = None
    business_justification: Annotated[str | None, Field(default=None, max_length=2000)] = None

    @field_validator("git_repository")
    @classmethod
    def _check_repo(cls, value: str) -> str:
        return _validate_repo(value)

    @field_validator("jira_url")
    @classmethod
    def _check_jira_url(cls, value: str | None) -> str | None:
        return _validate_optional_url(value)


class BookingCreate(BookingBase):
    deployment_date: date
    slot_number: int = Field(ge=1, le=50)
    booking_pin: Pin
    confirm_booking_pin: Pin
    #: Admin-only knobs; ignored for public callers.
    override_weekly_limit: bool = False
    override_reason: str | None = Field(default=None, max_length=500)

    @field_validator("booking_pin", "confirm_booking_pin")
    @classmethod
    def _pins(cls, value: str) -> str:
        return _validate_pin(value)

    @model_validator(mode="after")
    def _pins_match(self) -> "BookingCreate":
        if self.booking_pin != self.confirm_booking_pin:
            raise ValueError("Booking PIN and confirmation do not match.")
        return self


class OwnerCredentials(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    requester_email: EmailStr
    booking_pin: Pin

    @field_validator("booking_pin")
    @classmethod
    def _pin(cls, value: str) -> str:
        return _validate_pin(value)


class BookingUpdate(BookingBase):
    """Public edits carry owner credentials; admin edits carry an override reason."""

    deployment_date: date | None = None
    slot_number: int | None = Field(default=None, ge=1, le=50)
    credentials: OwnerCredentials | None = None
    override_weekly_limit: bool = False
    override_reason: str | None = Field(default=None, max_length=500)


class BookingCancel(BaseModel):
    credentials: OwnerCredentials | None = None
    override_reason: str | None = Field(default=None, max_length=500)


class MyBookingsRequest(OwnerCredentials):
    pass


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: DocumentCategory
    category_label: str
    original_filename: str
    size_bytes: int
    content_type: str | None
    uploaded_at: datetime


class DocumentStatus(BaseModel):
    category: DocumentCategory
    label: str
    required: bool
    provided: bool
    file_count: int


class DocumentReadiness(BaseModel):
    provided_required: int
    total_required: int
    percent: int
    complete: bool
    missing_labels: list[str]
    items: list[DocumentStatus]


class BookingSummary(BaseModel):
    """Fields safe to show on the public weekly board."""

    id: int
    booking_reference: str
    tenant_name: str
    deployment_date: date
    slot_number: int
    jira_change: str
    jira_task: str | None
    jira_url: str | None
    technology: str
    environment: str
    verifier_name: str
    status: str
    is_emergency: bool
    is_locked: bool
    lock_deadline: datetime | None
    documents: DocumentReadiness
    created_at: datetime
    updated_at: datetime


class BookingDetail(BookingSummary):
    """Adds contact details; only returned to the owner or an admin."""

    requester_name: str
    requester_email: str
    requester_phone: str | None
    verifier_email: str
    git_repository: str
    implementation_summary: str
    deployment_description: str
    additional_comments: str | None
    emergency_reason: str | None
    emergency_approval_reference: str | None
    emergency_approver: str | None
    business_justification: str | None
    cancelled_at: datetime | None
    created_by_admin: str | None
    attachments: list[AttachmentOut]
    can_edit: bool
    slot_label: str
    slot_time: str


class BookingCreated(BaseModel):
    booking: BookingDetail
    manage_token: str
    manage_url: str
    message: str


class AuditEventOut(BaseModel):
    id: int
    booking_reference: str | None
    event_type: str
    actor_type: Literal["PUBLIC", "ADMIN", "SYSTEM"]
    requester_email: str | None
    admin_username: str | None
    override_reason: str | None
    old_values: dict | None
    new_values: dict | None
    created_at: datetime


class SlotView(BaseModel):
    slot_number: int
    name: str
    start_time: time
    end_time: time
    time_label: str
    is_emergency: bool
    enabled: bool
    unavailable_reason: str | None
    state: Literal["AVAILABLE", "BOOKED", "HOLIDAY", "DISABLED", "EMERGENCY_AVAILABLE"]
    bookable_by_public: bool
    bookable_by_admin: bool
    booking: BookingSummary | None


class HolidayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    holiday_date: date
    name: str
    description: str | None
    is_full_day: bool
    allow_emergency: bool


class DailyOverrideOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    override_date: date
    regular_slots: int | None
    emergency_enabled: bool | None
    note: str | None


class DayView(BaseModel):
    day: date
    weekday: str
    date_label: str
    is_today: bool
    is_past: bool
    holiday: HolidayOut | None
    override: DailyOverrideOut | None
    regular_slots_total: int
    regular_slots_used: int
    slots: list[SlotView]


class ScheduleSummary(BaseModel):
    regular_slots_total: int
    regular_slots_available: int
    slots_booked: int
    holidays: int
    emergency_slots_total: int
    emergency_slots_booked: int


class ScheduleResponse(BaseModel):
    week_start: date
    week_end: date
    week_label: str
    today: date
    timezone: str
    days: list[DayView]
    summary: ScheduleSummary
    settings: "PublicSettings"


class PublicSettings(BaseModel):
    weekly_booking_limit: int
    booking_freeze_hours: int
    max_file_size_mb: int
    mandatory_documents: list[str]
    document_catalog: list[dict]
    technologies: list[str]


ScheduleResponse.model_rebuild()
