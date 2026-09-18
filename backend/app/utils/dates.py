"""Date/time helpers.

The scheduler is an India-facing tool: all business days, slot times and the
48-hour freeze window are reasoned about in Asia/Kolkata, while every stored
timestamp is UTC.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from ..config import settings

LOCAL_TZ = ZoneInfo(settings.timezone)

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def now_utc() -> datetime:
    """Naive UTC, matching how timestamps are stored."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today_local() -> date:
    return datetime.now(LOCAL_TZ).date()


def week_start(any_day: date) -> date:
    """Monday of the calendar week containing ``any_day``."""
    return any_day - timedelta(days=any_day.weekday())


def working_week(monday: date) -> list[date]:
    return [monday + timedelta(days=i) for i in range(5)]


def local_datetime(day: date, at: time) -> datetime:
    return datetime.combine(day, at, tzinfo=LOCAL_TZ)


def to_utc_naive(aware: datetime) -> datetime:
    return aware.astimezone(timezone.utc).replace(tzinfo=None)


def slot_start_utc(day: date, start: time) -> datetime:
    return to_utc_naive(local_datetime(day, start))


def format_day(day: date) -> str:
    """e.g. ``17 Sep 2026``."""
    return f"{day.day:02d} {day.strftime('%b')} {day.year}"


def format_time(at: time) -> str:
    """e.g. ``10:30 AM``."""
    return at.strftime("%I:%M %p")


def format_week_range(monday: date) -> str:
    friday = monday + timedelta(days=4)
    if monday.month == friday.month:
        return f"{monday.day:02d} - {friday.day:02d} {friday.strftime('%b')} {friday.year}"
    return f"{monday.day:02d} {monday.strftime('%b')} - {friday.day:02d} {friday.strftime('%b')} {friday.year}"
