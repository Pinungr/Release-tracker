"""Date helpers for the Production Deployment Scheduler.

Business scheduling is date-only in Asia/Kolkata. Normal deployment days are
Sunday through Thursday. Friday and Saturday are non-deployment days.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from ..config import settings

LOCAL_TZ = ZoneInfo(settings.timezone)
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DEPLOYMENT_WEEKDAYS = {6, 0, 1, 2, 3}  # Sunday .. Thursday (Python Monday=0)


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today_local() -> date:
    return datetime.now(LOCAL_TZ).date()


def is_deployment_weekday(day: date) -> bool:
    return day.weekday() in DEPLOYMENT_WEEKDAYS


def week_start(any_day: date) -> date:
    """Sunday of the deployment week containing ``any_day``."""
    days_since_sunday = (any_day.weekday() + 1) % 7
    return any_day - timedelta(days=days_since_sunday)


def working_week(sunday: date, *, include_weekend: bool = False) -> list[date]:
    """The five normal deployment dates: Sunday through Thursday.

    ``include_weekend`` is retained for API compatibility; Friday/Saturday are
    never normal deployment rows.
    """
    return [sunday + timedelta(days=i) for i in range(5)]


def local_datetime(day: date, at: time) -> datetime:
    return datetime.combine(day, at, tzinfo=LOCAL_TZ)


def to_utc_naive(aware: datetime) -> datetime:
    return aware.astimezone(timezone.utc).replace(tzinfo=None)


def slot_start_utc(day: date, start: time) -> datetime:
    return to_utc_naive(local_datetime(day, start))


def format_day(day: date) -> str:
    return f"{day.day:02d} {day.strftime('%b')} {day.year}"


def format_time(at: time) -> str:
    return at.strftime("%I:%M %p")


def format_week_range(sunday: date, *, include_weekend: bool = False) -> str:
    end = sunday + timedelta(days=4)
    if sunday.month == end.month:
        return f"{sunday.day:02d} - {end.day:02d} {end.strftime('%b')} {end.year}"
    return f"{sunday.day:02d} {sunday.strftime('%b')} - {end.day:02d} {end.strftime('%b')} {end.year}"
