"""Tenant search, schedule history and the shared date-window rule.

Every query here filters and pages in the database; nothing loads a whole
history to be filtered in Python.

Visibility: any signed-in user may read any change record (see
``api.bookings._assert_can_view``), so schedule search and history are not
narrowed per user. The Central Audit is narrowed by its own route, which is
restricted to the Owner and Release Managers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from ..models import BookingAssignment, BookingStatus, DeploymentBooking, Tenant
from ..schemas.booking import ScheduleListItem, TenantUpcoming, UpcomingWeek
from ..utils.dates import LOCAL_TZ, format_week_range, today_local, week_start

#: Existing statuses that mean "still going to happen". Terminal outcomes
#: (completed, cancelled, succeeded, failed, rolled back) belong to History.
OPEN_STATUSES = (
    BookingStatus.BOOKED.value,
    BookingStatus.LOCKED.value,
    BookingStatus.IN_PROGRESS.value,
    BookingStatus.VALIDATION_PENDING.value,
)

#: Relative ranges offered by the UI. Any value in range is accepted.
MAX_DAYS = 366
UPCOMING_LIMIT = 200


# --------------------------------------------------------------------------- #
# Date window: Days XOR From/To
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DateWindow:
    """An inclusive local-date range; either end may be open."""

    start: date | None
    end: date | None

    def utc_bounds(self) -> tuple[datetime | None, datetime | None]:
        """UTC [start, end) for filtering timestamps stored in UTC.

        Audit times are stored as naive UTC, but people pick dates in the
        business time zone, so "15 Sep" means 15 Sep in that zone.
        """
        def utc(day: date) -> datetime:
            local = datetime.combine(day, time.min, tzinfo=LOCAL_TZ)
            return local.astimezone(timezone.utc).replace(tzinfo=None)

        return (
            utc(self.start) if self.start else None,
            utc(self.end + timedelta(days=1)) if self.end else None,
        )


def date_window(
    days: int | None, date_from: date | None, date_to: date | None
) -> DateWindow:
    """Resolve the filter trio into one unambiguous window.

    ``days`` and a custom From/To range are mutually exclusive. The UI clears
    one when the other is chosen; the API refuses contradictory input rather
    than silently picking a winner.
    """
    if days is not None and (date_from is not None or date_to is not None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Choose either a Days range or a From/To date range, not both.",
        )
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "From date must be on or before To date."
        )
    if days is not None:
        today = today_local()
        # "Last 7 days" = today and the six days before it.
        return DateWindow(start=today - timedelta(days=days - 1), end=today)
    return DateWindow(start=date_from, end=date_to)


# --------------------------------------------------------------------------- #
# Tenants
# --------------------------------------------------------------------------- #


def lookup_tenants(db: Session, query: str, *, limit: int = 10) -> list[Tenant]:
    """Tenant autocomplete: name or code contains the term, active first.

    Inactive tenants are included because their history is still searchable.
    """
    term = query.strip()
    stmt = select(Tenant)
    if term:
        stmt = stmt.where(or_(
            Tenant.name.icontains(term, autoescape=True),
            Tenant.tenant_code.icontains(term, autoescape=True),
        ))
    return list(db.scalars(
        stmt.order_by(Tenant.is_active.desc(), Tenant.name, Tenant.id).limit(limit)
    ).all())


def get_tenant(db: Session, tenant_id: int) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found.")
    return tenant


# --------------------------------------------------------------------------- #
# Schedules
# --------------------------------------------------------------------------- #


def list_item(booking: DeploymentBooking) -> ScheduleListItem:
    return ScheduleListItem(
        id=booking.id,
        booking_reference=booking.booking_reference,
        tenant_id=booking.tenant_id,
        tenant_name=booking.tenant_name,
        deployment_date=booking.deployment_date,
        slot_number=booking.slot_number,
        is_emergency=booking.is_emergency,
        status=booking.status,
        change_number=booking.change_number,
        jira_number=booking.jira_number,
        jira_url=booking.jira_url,
        release_managers=[
            a.user.full_name for a in sorted(booking.assignments, key=lambda item: item.id)
        ],
    )


def _with_managers(stmt):
    # Load Release Managers for the page in one extra query, not one per row.
    return stmt.options(
        selectinload(DeploymentBooking.assignments).selectinload(BookingAssignment.user)
    )


def tenant_upcoming(db: Session, tenant: Tenant) -> TenantUpcoming:
    """The tenant's open schedules from today onward, grouped by deployment week.

    Only this tenant's schedules are returned, and a week appears only when it
    holds at least one of them, so empty weeks and other tenants' schedules in
    the same week never show up.
    """
    rows = list(db.scalars(_with_managers(
        select(DeploymentBooking)
        .where(
            DeploymentBooking.tenant_id == tenant.id,
            DeploymentBooking.deployment_date >= today_local(),
            DeploymentBooking.status.in_(OPEN_STATUSES),
        )
        # Nearest first; slot then id keep same-day order deterministic, with
        # emergency changes (no slot) after the numbered slots of that day.
        .order_by(
            DeploymentBooking.deployment_date,
            DeploymentBooking.slot_number.is_(None),
            DeploymentBooking.slot_number,
            DeploymentBooking.id,
        )
        .limit(UPCOMING_LIMIT + 1)
    )).all())

    truncated = len(rows) > UPCOMING_LIMIT
    weeks: list[UpcomingWeek] = []
    for booking in rows[:UPCOMING_LIMIT]:
        sunday = week_start(booking.deployment_date)
        if not weeks or weeks[-1].week_start != sunday:
            weeks.append(UpcomingWeek(
                week_start=sunday,
                week_end=sunday + timedelta(days=4),
                week_label=format_week_range(sunday),
                schedules=[],
            ))
        weeks[-1].schedules.append(list_item(booking))

    return TenantUpcoming(
        tenant_id=tenant.id, tenant_name=tenant.name, weeks=weeks, truncated=truncated
    )


def schedule_history(
    db: Session,
    *,
    tenant_id: int | None,
    window: DateWindow,
    before: tuple[date, int] | None,
    limit: int,
) -> list[ScheduleListItem]:
    """Schedules of every status, newest deployment date first.

    Without any date filter the history is the past: deployment dates up to
    today. An explicit From/To range is honoured exactly, even into the future.
    Paging is keyset on (deployment_date, id), matching the sort, so deep pages
    stay as cheap as the first.
    """
    stmt = select(DeploymentBooking)
    if tenant_id is not None:
        stmt = stmt.where(DeploymentBooking.tenant_id == tenant_id)
    start, end = window.start, window.end
    if start is None and end is None:
        end = today_local()
    if start is not None:
        stmt = stmt.where(DeploymentBooking.deployment_date >= start)
    if end is not None:
        stmt = stmt.where(DeploymentBooking.deployment_date <= end)
    if before is not None:
        before_date, before_id = before
        stmt = stmt.where(or_(
            DeploymentBooking.deployment_date < before_date,
            (DeploymentBooking.deployment_date == before_date) & (DeploymentBooking.id < before_id),
        ))
    rows = db.scalars(_with_managers(
        stmt.order_by(DeploymentBooking.deployment_date.desc(), DeploymentBooking.id.desc())
        .limit(limit)
    )).all()
    return [list_item(b) for b in rows]
