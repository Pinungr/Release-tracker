"""Read-only availability lookup built from the schedule board's bookable state."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..utils.dates import today_local, week_start
from . import presenters

NEXT_SLOT_SEARCH_DAYS = 60


def next_available_slot(
    db: Session, *, search_days: int = NEXT_SLOT_SEARCH_DAYS
) -> dict[str, Any]:
    """Return the earliest currently bookable normal slot within the horizon."""
    today = today_local()
    first_date = today + timedelta(days=1)
    search_through = today + timedelta(days=max(1, search_days))
    week = week_start(first_date)

    while week <= search_through:
        schedule = presenters.schedule_response(db, week, is_admin=False)
        for day in schedule.days:
            if day.day < first_date or day.day > search_through:
                continue
            for slot in day.slots:
                if slot.bookable:
                    return {
                        "available": True,
                        "deployment_date": day.day.isoformat(),
                        "weekday": day.weekday,
                        "slot_number": slot.slot_number,
                        "slot_name": slot.name,
                        "time_label": slot.time_label,
                        "week_start": schedule.week_start.isoformat(),
                        "search_through": search_through.isoformat(),
                        "search_days": max(1, search_days),
                    }
        week += timedelta(days=7)

    return {
        "available": False,
        "deployment_date": None,
        "weekday": None,
        "slot_number": None,
        "slot_name": None,
        "time_label": None,
        "week_start": None,
        "search_through": search_through.isoformat(),
        "search_days": max(1, search_days),
    }
