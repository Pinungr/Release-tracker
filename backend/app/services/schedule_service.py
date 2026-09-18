"""Resolution of the weekly board: slot grid, holidays, per-day overrides.

Every rule here is also re-checked by ``booking_service`` before a write; this
module exists so the read model and the write validations share one definition
of "is this slot bookable".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    ACTIVE_STATUSES,
    DailySlotOverride,
    DeploymentBooking,
    DeploymentSlotConfiguration,
    Holiday,
)
from ..utils.dates import week_start, working_week
from .settings_service import AppSettings, get_app_settings


@dataclass(frozen=True)
class ResolvedSlot:
    slot_number: int
    name: str
    start_time: time
    end_time: time
    is_emergency: bool
    enabled: bool
    #: Set when the slot exists but cannot be booked at all on this date.
    unavailable_reason: str | None = None

    @property
    def bookable_by_public(self) -> bool:
        return self.enabled and not self.is_emergency and self.unavailable_reason is None

    @property
    def bookable_by_admin(self) -> bool:
        return self.enabled and self.unavailable_reason is None


@dataclass(frozen=True)
class DayPlan:
    day: date
    slots: list[ResolvedSlot]
    holiday: Holiday | None
    override: DailySlotOverride | None

    @property
    def regular_slots(self) -> list[ResolvedSlot]:
        return [s for s in self.slots if not s.is_emergency]


def slot_configurations(db: Session) -> list[DeploymentSlotConfiguration]:
    return list(
        db.scalars(
            select(DeploymentSlotConfiguration).order_by(DeploymentSlotConfiguration.slot_number)
        ).all()
    )


def holidays_between(db: Session, start: date, end: date) -> dict[date, Holiday]:
    rows = db.scalars(
        select(Holiday).where(Holiday.holiday_date >= start, Holiday.holiday_date <= end)
    ).all()
    return {h.holiday_date: h for h in rows}


def overrides_between(db: Session, start: date, end: date) -> dict[date, DailySlotOverride]:
    rows = db.scalars(
        select(DailySlotOverride).where(
            DailySlotOverride.override_date >= start, DailySlotOverride.override_date <= end
        )
    ).all()
    return {o.override_date: o for o in rows}


def resolve_day(
    db: Session,
    day: date,
    *,
    app_settings: AppSettings | None = None,
    configs: list[DeploymentSlotConfiguration] | None = None,
    holiday: Holiday | None = None,
    override: DailySlotOverride | None = None,
    prefetched: bool = False,
) -> DayPlan:
    app_settings = app_settings or get_app_settings(db)
    configs = configs if configs is not None else slot_configurations(db)
    if not prefetched:
        holiday = holidays_between(db, day, day).get(day)
        override = overrides_between(db, day, day).get(day)

    regular_limit = app_settings.regular_slots_per_day
    if override is not None and override.regular_slots is not None:
        regular_limit = override.regular_slots

    emergency_enabled = app_settings.emergency_slot_enabled
    if override is not None and override.emergency_enabled is not None:
        emergency_enabled = override.emergency_enabled

    full_day_holiday = holiday is not None and holiday.is_full_day
    weekend = day.weekday() >= 5

    slots: list[ResolvedSlot] = []
    regular_seen = 0
    for cfg in configs:
        if cfg.is_emergency:
            enabled = cfg.enabled and emergency_enabled
            reason: str | None = None
            if not enabled:
                reason = "Emergency slot disabled for this date."
            elif weekend:
                reason = "Outside the Monday-Friday deployment week."
            elif full_day_holiday and not holiday.allow_emergency:  # type: ignore[union-attr]
                reason = "Emergency deployments are not permitted on this holiday."
        else:
            regular_seen += 1
            enabled = cfg.enabled and regular_seen <= regular_limit
            reason = None
            if not enabled:
                reason = "Slot disabled for this date."
            elif weekend:
                reason = "Outside the Monday-Friday deployment week."
            elif full_day_holiday:
                reason = f"{holiday.name}: no production deployments available."  # type: ignore[union-attr]
            elif holiday is not None and not holiday.is_full_day:
                reason = None  # partial holiday: regular slots stay open
        slots.append(
            ResolvedSlot(
                slot_number=cfg.slot_number,
                name=cfg.name,
                start_time=cfg.start_time,
                end_time=cfg.end_time,
                is_emergency=cfg.is_emergency,
                enabled=enabled,
                unavailable_reason=reason,
            )
        )
    return DayPlan(day=day, slots=slots, holiday=holiday, override=override)


def resolve_week(db: Session, any_day: date) -> tuple[date, list[DayPlan], AppSettings]:
    monday = week_start(any_day)
    days = working_week(monday)
    app_settings = get_app_settings(db)
    configs = slot_configurations(db)
    holidays = holidays_between(db, days[0], days[-1])
    overrides = overrides_between(db, days[0], days[-1])
    plans = [
        resolve_day(
            db,
            day,
            app_settings=app_settings,
            configs=configs,
            holiday=holidays.get(day),
            override=overrides.get(day),
            prefetched=True,
        )
        for day in days
    ]
    return monday, plans, app_settings


def find_slot(db: Session, day: date, slot_number: int) -> ResolvedSlot | None:
    plan = resolve_day(db, day)
    for slot in plan.slots:
        if slot.slot_number == slot_number:
            return slot
    return None


def active_bookings_between(db: Session, start: date, end: date) -> list[DeploymentBooking]:
    return list(
        db.scalars(
            select(DeploymentBooking)
            .where(
                DeploymentBooking.deployment_date >= start,
                DeploymentBooking.deployment_date <= end,
                DeploymentBooking.status.in_(ACTIVE_STATUSES),
            )
            .order_by(DeploymentBooking.deployment_date, DeploymentBooking.slot_number)
        ).all()
    )
