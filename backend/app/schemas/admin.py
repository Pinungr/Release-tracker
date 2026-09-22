"""Admin request/response schemas."""
from __future__ import annotations

from datetime import date, time
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..models import DocumentCategory


class AdminLoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: Annotated[str, Field(min_length=1, max_length=64)]
    password: Annotated[str, Field(min_length=1, max_length=256)]


class AdminSession(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    username: str
    display_name: str


class SettingsOut(BaseModel):
    regular_slots_per_day: int
    weekly_booking_limit: int
    booking_freeze_dates: int
    jira_required_at_booking: bool
    max_file_size_mb: int
    emergency_changes_enabled: bool
    require_admin_override_reason: bool
    mandatory_documents: list[str]


class SettingsUpdate(BaseModel):
    regular_slots_per_day: int | None = Field(default=None, ge=1, le=12)
    weekly_booking_limit: int | None = Field(default=None, ge=1, le=25)
    booking_freeze_dates: int | None = Field(default=None, ge=0, le=25)
    jira_required_at_booking: bool | None = None
    max_file_size_mb: int | None = Field(default=None, ge=1, le=200)
    emergency_changes_enabled: bool | None = None
    require_admin_override_reason: bool | None = None
    mandatory_documents: list[DocumentCategory] | None = None


class SlotConfigIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    slot_number: int = Field(ge=1, le=50)
    name: Annotated[str, Field(min_length=1, max_length=80)]
    start_time: time
    end_time: time
    enabled: bool = True

    @model_validator(mode="after")
    def _ordered(self) -> "SlotConfigIn":
        # Overnight deployment windows are valid (for example 21:00 -> 05:00).
        # Equal start/end values are rejected because they are ambiguous.
        if self.end_time == self.start_time:
            raise ValueError("Slot start and end time cannot be the same.")
        return self


class SlotConfigOut(SlotConfigIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


class SlotConfigReplace(BaseModel):
    slots: list[SlotConfigIn] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _unique(self) -> "SlotConfigReplace":
        numbers = [s.slot_number for s in self.slots]
        if len(set(numbers)) != len(numbers):
            raise ValueError("Slot numbers must be unique.")
        return self


class HolidayIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    holiday_date: date
    name: Annotated[str, Field(min_length=1, max_length=160)]
    description: Annotated[str | None, Field(default=None, max_length=1000)] = None
    is_full_day: bool = True
    allow_emergency: bool = True


class DaySlotCapacityOut(BaseModel):
    """Normal slot capacity for one deployment date."""

    capacity_date: date
    #: Slots actually offered on this date.
    slot_count: int
    #: ``None`` when the date follows the configured default.
    custom_slot_count: int | None
    max_slot_count: int


class MoveBookingRequest(BaseModel):
    deployment_date: date
    # Emergency changes have no normal slot and may be moved by date only.
    slot_number: int | None = Field(default=None, ge=1, le=50)
    override_reason: Annotated[str | None, Field(default=None, max_length=500)] = None


class ReassignBookingRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    tenant_id: int | None = Field(default=None, ge=1)
    requester_name: Annotated[str | None, Field(default=None, max_length=120)] = None
    requester_email: Annotated[str | None, Field(default=None, max_length=180)] = None
    verifier_name: Annotated[str | None, Field(default=None, max_length=120)] = None
    verifier_email: Annotated[str | None, Field(default=None, max_length=180)] = None
    override_reason: Annotated[str | None, Field(default=None, max_length=500)] = None


class AssignUsersRequest(BaseModel):
    user_ids: list[int] = Field(min_length=1, max_length=50)


class StatusUpdateRequest(BaseModel):
    status: str
    override_reason: Annotated[str | None, Field(default=None, max_length=500)] = None


class SlotFreezeRequest(BaseModel):
    freeze_date: date
    slot_number: int = Field(ge=1, le=50)
    note: Annotated[str | None, Field(default=None, max_length=255)] = None


class SlotFreezeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    freeze_date: date
    slot_number: int
    note: str | None
