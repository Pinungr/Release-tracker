"""Request/response schemas for the authenticated booking API."""
from __future__ import annotations

import re
from datetime import date, datetime, time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from ..models import DocumentCategory, Technology

_HTTP_URL = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)
_SCP_GIT = re.compile(r"^(git|ssh)://[^\s]+$|^[\w.-]+@[\w.-]+:[\w./~-]+$", re.IGNORECASE)

ShortText = Annotated[str, Field(min_length=1, max_length=120)]


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

    tenant_id: int = Field(ge=1)
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
    slot_number: int | None = Field(default=None, ge=1, le=50)
    is_emergency: bool = False
    #: Administrator-only knobs; rejected for TENANT_USER callers.
    override_weekly_limit: bool = False
    override_reason: str | None = Field(default=None, max_length=500)

class BookingUpdate(BookingBase):
    """Authenticated owners edit their own bookings; admins may edit any booking."""

    deployment_date: date | None = None
    slot_number: int | None = Field(default=None, ge=1, le=50)
    override_weekly_limit: bool = False
    override_reason: str | None = Field(default=None, max_length=500)


class BookingCancel(BaseModel):
    override_reason: str | None = Field(default=None, max_length=500)


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
    """Row-level view of a change record on the weekly board."""

    id: int
    booking_reference: str
    tenant_id: int
    tenant_name: str
    deployment_date: date
    slot_number: int | None
    jira_change: str
    jira_task: str | None
    jira_url: str | None
    technology: str
    environment: str
    verifier_name: str
    status: str
    is_emergency: bool
    created_by_user_id: int | None
    is_locked: bool
    lock_deadline: datetime | None
    documents: DocumentReadiness
    created_at: datetime
    updated_at: datetime


class BookingDetail(BookingSummary):
    """Full record. Only ever returned to its owner or an administrator."""

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
    attachments: list[AttachmentOut]
    can_edit: bool
    slot_label: str
    slot_time: str


class BookingCreated(BaseModel):
    booking: BookingDetail
    message: str


class AuditEventOut(BaseModel):
    id: int
    booking_reference: str | None
    event_type: str
    actor_type: Literal["USER", "ADMIN", "SYSTEM"]
    requester_email: str | None
    admin_username: str | None
    override_reason: str | None
    old_values: dict | None
    new_values: dict | None
    created_at: datetime


class SlotView(BaseModel):
    """One normal deployment slot. Emergency changes are not slots."""

    slot_number: int
    name: str
    start_time: time
    end_time: time
    time_label: str
    enabled: bool
    unavailable_reason: str | None
    state: Literal["AVAILABLE", "BOOKED", "HOLIDAY", "DISABLED"]
    bookable: bool
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
    #: Emergency changes are an admin-only queue on the date, not a slot.
    emergency_open: bool
    emergency_closed_reason: str | None
    emergency_bookings: list[BookingSummary]


class ScheduleSummary(BaseModel):
    regular_slots_total: int
    regular_slots_available: int
    slots_booked: int
    holidays: int
    #: Emergency changes scheduled this week (any number per date).
    emergency_changes: int


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
