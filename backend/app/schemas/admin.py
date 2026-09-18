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
    booking_freeze_hours: int
    max_file_size_mb: int
    emergency_slot_enabled: bool
    require_admin_override_reason: bool
    mandatory_documents: list[str]


class SettingsUpdate(BaseModel):
    regular_slots_per_day: int | None = Field(default=None, ge=1, le=12)
    weekly_booking_limit: int | None = Field(default=None, ge=1, le=25)
    booking_freeze_hours: int | None = Field(default=None, ge=0, le=720)
    max_file_size_mb: int | None = Field(default=None, ge=1, le=200)
    emergency_slot_enabled: bool | None = None
    require_admin_override_reason: bool | None = None
    mandatory_documents: list[DocumentCategory] | None = None


class SlotConfigIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    slot_number: int = Field(ge=1, le=50)
    name: Annotated[str, Field(min_length=1, max_length=80)]
    start_time: time
    end_time: time
    is_emergency: bool = False
    enabled: bool = True

    @model_validator(mode="after")
    def _ordered(self) -> "SlotConfigIn":
        if self.end_time <= self.start_time:
            raise ValueError("Slot end time must be after the start time.")
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


class DailyOverrideIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    override_date: date
    regular_slots: int | None = Field(default=None, ge=0, le=12)
    emergency_enabled: bool | None = None
    note: Annotated[str | None, Field(default=None, max_length=255)] = None


class MoveBookingRequest(BaseModel):
    deployment_date: date
    slot_number: int = Field(ge=1, le=50)
    override_reason: Annotated[str | None, Field(default=None, max_length=500)] = None


class ReassignBookingRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    tenant_name: Annotated[str | None, Field(default=None, max_length=120)] = None
    requester_name: Annotated[str | None, Field(default=None, max_length=120)] = None
    requester_email: Annotated[str | None, Field(default=None, max_length=180)] = None
    verifier_name: Annotated[str | None, Field(default=None, max_length=120)] = None
    verifier_email: Annotated[str | None, Field(default=None, max_length=180)] = None
    override_reason: Annotated[str | None, Field(default=None, max_length=500)] = None


class StatusUpdateRequest(BaseModel):
    status: str
    override_reason: Annotated[str | None, Field(default=None, max_length=500)] = None
