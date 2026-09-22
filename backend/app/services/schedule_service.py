"""Resolution of the weekly board: normal slot grid, holidays, per-date capacity.

Every rule here is also re-checked by ``booking_service`` before a write; this
module exists so the read model and the write validations share one definition
of "is this slot bookable".

Emergency changes are deliberately absent from the slot grid. They are an
admin-only queue attached to a date (``emergency_bookings_between``), never a
slot, so any number of them can exist on the same day.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    ACTIVE_STATUSES,
    DailySlotCapacity,
    DeploymentBooking,
    DeploymentSlotConfiguration,
    Holiday,
)
from ..utils.dates import is_deployment_weekday, week_start, working_week
from .settings_service import AppSettings, get_app_settings


@dataclass(frozen=True)
class ResolvedSlot:
    """One normal deployment slot on one date."""

    slot_number: int
    name: str
    start_time: time
    end_time: time
    enabled: bool
    #: Set when the slot exists but cannot be booked at all on this date.
    unavailable_reason: str | None = None

    @property
    def bookable(self) -> bool:
        return self.enabled and self.unavailable_reason is None


@dataclass(frozen=True)
class DayPlan:
    day: date
    slots: list[ResolvedSlot]
    holiday: Holiday | None
    #: Effective number of normal slots offered on this date.
    normal_slot_count: int
    #: Configured date limit, independent of disabled or missing rows.
    configured_slot_count: int
    #: Set only when an administrator added/removed slots on this date; ``None``
    #: means the date simply follows the configured default.
    custom_slot_count: int | None = None
    #: Whether an administrator may add an emergency change to this date.
    emergency_open: bool = True
    emergency_closed_reason: str | None = None


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


def capacities_between(db: Session, start: date, end: date) -> dict[date, DailySlotCapacity]:
    rows = db.scalars(
        select(DailySlotCapacity).where(
            DailySlotCapacity.capacity_date >= start, DailySlotCapacity.capacity_date <= end
        )
    ).all()
    return {row.capacity_date: row for row in rows}


def resolve_day(
    db: Session,
    day: date,
    *,
    app_settings: AppSettings | None = None,
    configs: list[DeploymentSlotConfiguration] | None = None,
    holiday: Holiday | None = None,
    capacity: DailySlotCapacity | None = None,
    prefetched: bool = False,
) -> DayPlan:
    app_settings = app_settings or get_app_settings(db)
    configs = configs if configs is not None else slot_configurations(db)
    if not prefetched:
        holiday = holidays_between(db, day, day).get(day)
        capacity = capacities_between(db, day, day).get(day)

    # The default slot count applies to every deployment date; a capacity row
    # exists only where an administrator added or removed slots for that date.
    custom_slot_count = capacity.slot_count if capacity is not None else None
    regular_limit = (
        custom_slot_count if custom_slot_count is not None else app_settings.regular_slots_per_day
    )

    # Emergency changes are a separate per-date admin queue, never a slot, so
    # per-date normal capacity has no bearing on whether they are open.
    emergency_enabled = app_settings.emergency_changes_enabled

    full_day_holiday = holiday is not None and holiday.is_full_day
    outside_deployment_week = not is_deployment_weekday(day)

    # The grid keeps every configured slot row on every date. Rows above the
    # date's capacity are reported disabled rather than removed, so a booking
    # is never hidden by a capacity change and administrators keep their
    # explicit manual override workflow.
    slots: list[ResolvedSlot] = []
    for cfg in configs:
        enabled = cfg.enabled and cfg.slot_number <= regular_limit
        reason: str | None = None
        if not enabled:
            reason = "Slot disabled for this date."
        elif outside_deployment_week:
            reason = "Outside the Sunday-Thursday deployment week."
        elif full_day_holiday:
            reason = f"{holiday.name}: no production deployments available."  # type: ignore[union-attr]
        slots.append(
            ResolvedSlot(
                slot_number=cfg.slot_number,
                name=cfg.name,
                start_time=cfg.start_time,
                end_time=cfg.end_time,
                enabled=enabled,
                unavailable_reason=reason,
            )
        )

    # Emergency changes are governed by the date, not by a slot.
    emergency_closed: str | None = None
    if not emergency_enabled:
        emergency_closed = "Emergency changes are disabled for this date."
    elif outside_deployment_week:
        emergency_closed = "Outside the Sunday-Thursday deployment week."
    elif full_day_holiday and not holiday.allow_emergency:  # type: ignore[union-attr]
        emergency_closed = "Emergency deployments are not permitted on this holiday."

    return DayPlan(
        day=day,
        slots=slots,
        holiday=holiday,
        normal_slot_count=sum(1 for s in slots if s.enabled),
        configured_slot_count=regular_limit,
        custom_slot_count=custom_slot_count,
        emergency_open=emergency_closed is None,
        emergency_closed_reason=emergency_closed,
    )


def resolve_week(
    db: Session, any_day: date, *, include_weekend: bool = False
) -> tuple[date, list[DayPlan], AppSettings]:
    sunday = week_start(any_day)
    days = working_week(sunday, include_weekend=include_weekend)
    app_settings = get_app_settings(db)
    configs = slot_configurations(db)
    holidays = holidays_between(db, days[0], days[-1])
    capacities = capacities_between(db, days[0], days[-1])
    plans = [
        resolve_day(
            db,
            day,
            app_settings=app_settings,
            configs=configs,
            holiday=holidays.get(day),
            capacity=capacities.get(day),
            prefetched=True,
        )
        for day in days
    ]
    return sunday, plans, app_settings


def find_slot(db: Session, day: date, slot_number: int | None) -> ResolvedSlot | None:
    """Emergency changes carry no slot number, so ``None`` never resolves."""
    if slot_number is None:
        return None
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


def emergency_bookings_between(db: Session, start: date, end: date) -> list[DeploymentBooking]:
    return list(
        db.scalars(
            select(DeploymentBooking)
            .where(
                DeploymentBooking.deployment_date >= start,
                DeploymentBooking.deployment_date <= end,
                DeploymentBooking.is_emergency.is_(True),
                DeploymentBooking.status.in_(ACTIVE_STATUSES),
            )
            .order_by(DeploymentBooking.deployment_date, DeploymentBooking.id)
        ).all()
    )
