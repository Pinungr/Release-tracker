"""Weekly board. Visible to any authenticated account."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import ScheduleResponse
from ..security import UserPrincipal, require_user
from ..services import presenters
from ..utils.dates import today_local

router = APIRouter(tags=["schedule"])


@router.get("/schedule", response_model=ScheduleResponse)
def get_schedule(
    week: str | None = Query(default=None, description="Any date inside the desired week (YYYY-MM-DD)."),
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
    return presenters.schedule_response(db, anchor)
