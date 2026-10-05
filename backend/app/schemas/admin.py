"""Admin request/response schemas."""
from __future__ import annotations

from datetime import date, time
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SettingsOut(BaseModel):
    regular_slots_per_day: int
    weekly_booking_limit: int
    booking_freeze_dates: int
    jira_required_at_booking: bool
    max_file_size_mb: int


class SettingsUpdate(BaseModel):
    regular_slots_per_day: int | None = Field(default=None, ge=1, le=12)
    weekly_booking_limit: int | None = Field(default=None, ge=1, le=25)
    booking_freeze_dates: int | None = Field(default=None, ge=0, le=25)
    jira_required_at_booking: bool | None = None
    max_file_size_mb: int | None = Field(default=None, ge=1, le=200)


class TeamsNotificationSettingsOut(BaseModel):
    enabled: bool
    webhook_configured: bool
    #: False when the saved webhook is not an accepted Teams Workflows URL (it is never called).
    webhook_valid: bool = False


class TeamsNotificationSettingsUpdate(BaseModel):
    enabled: bool | None = None
    webhook_url: Annotated[str | None, Field(default=None, max_length=4000)] = None
    clear_webhook: bool = False


class AITenantAccessUpdate(BaseModel):
    tenant_id: int = Field(ge=1)
    enabled: bool


class AIAccessUpdate(BaseModel):
    ai_enabled: bool | None = None
    management_enabled: bool | None = None
    release_managers_enabled: bool | None = None
    tenants: list[AITenantAccessUpdate] | None = None


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


class DaySlotCapacityOut(BaseModel):
    """Normal slot capacity for one deployment date."""

    capacity_date: date
    #: Slots actually offered on this date.
    slot_count: int
    #: ``None`` when the date follows the configured default.
    custom_slot_count: int | None
    max_slot_count: int


class MoveBookingRequest(BaseModel):
    manual_override: bool = False
    deployment_date: date
    # Emergency changes have no normal slot and may be moved by date only.
    slot_number: int | None = Field(default=None, ge=1, le=50)
    override_reason: Annotated[str | None, Field(default=None, max_length=500)] = None



class AssignUsersRequest(BaseModel):
    user_ids: list[int] = Field(min_length=1, max_length=1)


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


class LockOverrideRequest(BaseModel):
    override_date: date
    #: Omit to unlock the whole date (every slot and the emergency queue).
    slot_number: int | None = Field(default=None, ge=1, le=50)
    reason: Annotated[str | None, Field(default=None, max_length=255)] = None


class LockOverrideOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    override_date: date
    slot_number: int | None
    reason: str | None


class DocumentTypeCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    label: Annotated[str, Field(min_length=1, max_length=120)]
    #: Optional stable identifier; derived from the label when omitted.
    key: Annotated[str | None, Field(default=None, max_length=40)] = None
    description: Annotated[str | None, Field(default=None, max_length=1000)] = None
    is_required: bool = False
    allow_multiple: bool = False
    is_active: bool = True


class DocumentTypeUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    label: Annotated[str | None, Field(default=None, min_length=1, max_length=120)] = None
    description: Annotated[str | None, Field(default=None, max_length=1000)] = None
    is_required: bool | None = None
    allow_multiple: bool | None = None
    is_active: bool | None = None


class DocumentTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    label: str
    description: str | None
    is_active: bool
    is_required: bool
    allow_multiple: bool
    display_order: int
    #: Uploaded files that reference this type (such a type can only be disabled).
    file_count: int = 0
    #: Schedules holding more than one file of this type. For a Single File
    #: type these predate a Multiple -> Single switch and are kept as they are.
    multi_file_schedules: int = 0


class DocumentTypeOrder(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)
