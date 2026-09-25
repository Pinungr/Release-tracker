"""Weekly board. Visible to any authenticated account."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import ScheduleResponse
from ..schemas.booking import NextAvailableSlot
from ..security import UserPrincipal, require_user
from ..services import presenters
from ..utils.dates import is_deployment_weekday, today_local, week_start

router = APIRouter(tags=["schedule"])


@router.get("/schedule", response_model=ScheduleResponse)
def get_schedule(
    week: str | None = Query(default=None, description="Any date inside the desired week (YYYY-MM-DD)."),
    first_available: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_user),
) -> ScheduleResponse:
    """Only the requested week is loaded; navigation refetches per week."""
    if week:
        try:
            anchor = date.fromisoformat(week)
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "week must be YYYY-MM-DD.") from None
    else:
        anchor = today_local()
    if first_available and not user.is_admin:
        return _tenant_landing(db)
    return presenters.schedule_response(db, anchor, is_admin=user.is_admin)


#: How far ahead the landing view looks for the next free slot.
NEXT_AVAILABLE_HORIZON_DAYS = 60


def _nearest_deployment_week(today: date) -> date:
    """Sunday of the week holding the next deployment date on or after today."""
    day = today
    while not is_deployment_weekday(day):
        day += timedelta(days=1)
    return week_start(day)


def _tenant_landing(db: Session) -> ScheduleResponse:
    """A tenant's first view: the nearest week, plus where the next free slot is.

    Tenants land on the nearest deployment week even when it is fully booked,
    so they see how busy the RM team already is. Jumping straight to the first
    week with a free slot would skip exactly the busiest weeks and show an
    empty board. The next free slot is reported separately so they can still
    go straight to it.
    """
    today = today_local()
    horizon = today + timedelta(days=NEXT_AVAILABLE_HORIZON_DAYS)
    landing = presenters.schedule_response(db, _nearest_deployment_week(today), is_admin=False)

    candidate = landing
    while True:
        slot_day = next(
            (
                (day, slot)
                for day in candidate.days
                if day.day <= horizon
                for slot in day.slots
                if slot.bookable
            ),
            None,
        )
        if slot_day is not None:
            day, slot = slot_day
            landing.next_available = NextAvailableSlot(
                deployment_date=day.day,
                week_start=candidate.week_start,
                weekday=day.weekday,
                date_label=day.date_label,
                slot_number=slot.slot_number,
                slot_name=slot.name,
                time_label=slot.time_label,
            )
            where = f"{day.weekday[:3]} {day.date_label} · {slot.name} ({slot.time_label})"
            landing.landing_message = (
                f"Next available slot: {where}."
                if candidate.week_start == landing.week_start
                else f"No free slot this week. Next available slot: {where}."
            )
            return landing
        next_week = candidate.week_start + timedelta(days=7)
        if next_week > horizon:
            landing.landing_message = (
                f"No bookable slots in the next {NEXT_AVAILABLE_HORIZON_DAYS} days. "
                "Contact a Release Manager or browse later weeks."
            )
            return landing
        candidate = presenters.schedule_response(db, next_week, is_admin=False)
