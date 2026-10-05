"""Read-only query service shared by the REST assistant API and MCP tools.

The AI layer never receives a database handle and never generates SQL.  Every
query is expressed through the small, parameterised functions in this module so
PDS remains the authority for data access and business semantics.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..models import AccessGroup, BookingAssignment, BookingStatus, DeploymentBooking, GroupMembership, Tenant, User
from ..utils.dates import today_local


DEPLOYMENT_OUTCOME_STATUSES = (
    BookingStatus.COMPLETED.value,
    BookingStatus.SUCCESSFUL.value,
    BookingStatus.FAILED.value,
    BookingStatus.ROLLED_BACK.value,
)


def count_users(db: Session, *, group: str | None = None, active_only: bool = False) -> dict[str, Any]:
    """Count accounts using real operational group memberships, without user details."""
    stmt = select(User.id, User.is_active)
    group_name = None
    if group and group.strip():
        term = group.strip()
        normalized_type = "_".join(term.upper().split())
        row = db.scalar(select(AccessGroup).where(
            or_(func.lower(AccessGroup.name) == term.lower(), AccessGroup.group_type == normalized_type)
        ).order_by(AccessGroup.is_system.desc(), AccessGroup.id))
        if row is None:
            raise HTTPException(404, f"User group '{term}' was not found.")
        group_name = row.name
        stmt = stmt.join(GroupMembership, GroupMembership.user_id == User.id).where(GroupMembership.group_id == row.id)
    if active_only:
        stmt = stmt.where(User.is_active.is_(True))
    rows = db.execute(stmt.distinct()).all()
    active = sum(bool(row.is_active) for row in rows)
    return {"group": group_name, "total": len(rows), "active": active, "inactive": len(rows) - active, "active_only": active_only}

MAX_ASSISTANT_RESULTS = 100


def _normalise_status(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalised = value.strip().upper().replace("-", "_").replace(" ", "_")
    allowed = {item.value for item in BookingStatus}
    if normalised not in allowed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Unknown schedule status '{value}'. Allowed values: {', '.join(sorted(allowed))}.",
        )
    return normalised


def _validate_dates(date_from: date | None, date_to: date | None) -> None:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "date_from must be on or before date_to.",
        )


def _resolve_tenant(db: Session, tenant: str | None) -> Tenant | None:
    if tenant is None or not tenant.strip():
        return None
    term = tenant.strip()
    row = db.scalar(
        select(Tenant).where(
            or_(
                func.lower(Tenant.name) == term.lower(),
                func.lower(Tenant.tenant_code) == term.lower(),
            )
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Tenant '{term}' was not found.")
    return row


def _apply_filters(
    stmt,
    *,
    tenant: Tenant | None,
    date_from: date | None,
    date_to: date | None,
    schedule_status: str | None,
    change_number: str | None = None,
    is_emergency: bool | None = None,
):
    _validate_dates(date_from, date_to)
    if tenant is not None:
        stmt = stmt.where(DeploymentBooking.tenant_id == tenant.id)
    if date_from is not None:
        stmt = stmt.where(DeploymentBooking.deployment_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(DeploymentBooking.deployment_date <= date_to)
    if schedule_status is not None:
        stmt = stmt.where(DeploymentBooking.status == schedule_status)
    if is_emergency is not None:
        stmt = stmt.where(DeploymentBooking.is_emergency.is_(is_emergency))
    if change_number is not None and change_number.strip():
        stmt = stmt.where(
            DeploymentBooking.change_number.icontains(change_number.strip(), autoescape=True)
        )
    return stmt


def _with_managers(stmt):
    return stmt.options(
        selectinload(DeploymentBooking.assignments).selectinload(BookingAssignment.user)
    )


def _schedule_payload(booking: DeploymentBooking) -> dict[str, Any]:
    managers = [
        {
            "user_id": assignment.user.id,
            "full_name": assignment.user.full_name,
            "username": assignment.user.username,
            "email": assignment.user.email,
            "assigned_at": assignment.assigned_at.isoformat() if assignment.assigned_at else None,
        }
        for assignment in sorted(booking.assignments, key=lambda item: item.id)
    ]
    return {
        "schedule_no": booking.booking_reference,
        "tenant": booking.tenant_name,
        "deployment_date": booking.deployment_date.isoformat(),
        "slot_number": booking.slot_number,
        "is_emergency": booking.is_emergency,
        "status": booking.status,
        "change_number": booking.change_number,
        "jira_number": booking.jira_number,
        "jira_url": booking.jira_url,
        "technology": booking.technology,
        "environment": booking.environment,
        "requester_name": booking.requester_name,
        "implementation_summary": booking.implementation_summary,
        "deployment_description": booking.deployment_description,
        "justification": booking.justification,
        "impacted_region": booking.impacted_region,
        "emergency_reason": booking.emergency_reason,
        "release_managers": managers,
    }


def get_schedule(db: Session, schedule_no: str) -> dict[str, Any]:
    """Return one schedule by its PDS schedule number."""
    reference = (schedule_no or "").strip()
    if not reference:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "schedule_no is required.")
    booking = db.scalar(
        _with_managers(
            select(DeploymentBooking).where(
                func.lower(DeploymentBooking.booking_reference) == reference.lower()
            )
        )
    )
    if booking is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Schedule '{reference}' was not found.")
    return _schedule_payload(booking)


def search_schedules(
    db: Session,
    *,
    tenant: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    schedule_status: str | None = None,
    is_emergency: bool | None = None,
    change_number: str | None = None,
    schedule_no: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Search schedules using approved, structured filters."""
    resolved_tenant = _resolve_tenant(db, tenant)
    normalised_status = _normalise_status(schedule_status)
    bounded_limit = max(1, min(int(limit), MAX_ASSISTANT_RESULTS))

    stmt = select(DeploymentBooking)
    stmt = _apply_filters(
        stmt,
        tenant=resolved_tenant,
        date_from=date_from,
        date_to=date_to,
        schedule_status=normalised_status,
        is_emergency=is_emergency,
        change_number=change_number,
    )
    if schedule_no is not None and schedule_no.strip():
        stmt = stmt.where(
            DeploymentBooking.booking_reference.icontains(schedule_no.strip(), autoescape=True)
        )
    rows = db.scalars(
        _with_managers(
            stmt.order_by(DeploymentBooking.deployment_date.desc(), DeploymentBooking.id.desc())
            .limit(bounded_limit)
        )
    ).all()
    return [_schedule_payload(row) for row in rows]


def count_schedules(
    db: Session,
    *,
    tenant: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    schedule_status: str | None = None,
    is_emergency: bool | None = None,
) -> dict[str, Any]:
    """Count schedules and return a small status/emergency breakdown."""
    resolved_tenant = _resolve_tenant(db, tenant)
    normalised_status = _normalise_status(schedule_status)

    stmt = select(DeploymentBooking.status, DeploymentBooking.is_emergency, func.count().label("quantity")).group_by(DeploymentBooking.status, DeploymentBooking.is_emergency)
    stmt = _apply_filters(
        stmt,
        tenant=resolved_tenant,
        date_from=date_from,
        date_to=date_to,
        schedule_status=normalised_status,
        is_emergency=is_emergency,
    )
    rows = db.execute(stmt).all()
    status_counts = Counter()
    for row in rows:
        status_counts[row.status] += row.quantity
    total = sum(row.quantity for row in rows)
    emergency_count = sum(row.quantity for row in rows if row.is_emergency)
    return {
        "tenant": resolved_tenant.name if resolved_tenant else None,
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "status_filter": normalised_status,
        "total": total,
        "normal": total - emergency_count,
        "emergency": emergency_count,
        "by_status": dict(sorted(status_counts.items())),
    }


def deployment_frequency(
    db: Session,
    *,
    tenant: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    is_emergency: bool | None = None,
) -> dict[str, Any]:
    """Return deterministic deployment cadence metrics for completed outcomes.

    A deployment is counted only after it reaches an execution outcome: COMPLETED,
    SUCCESSFUL, FAILED, or ROLLED_BACK. Cancelled and still-open bookings are not
    treated as deployments that happened. When the caller does not provide a
    period, the most recent 90-day window is used.
    """
    resolved_tenant = _resolve_tenant(db, tenant)
    end = date_to or today_local()
    start = date_from or (end - timedelta(days=90))
    _validate_dates(start, end)

    stmt = select(DeploymentBooking.deployment_date, DeploymentBooking.status)
    stmt = _apply_filters(
        stmt,
        tenant=resolved_tenant,
        date_from=start,
        date_to=end,
        schedule_status=None,
        is_emergency=is_emergency,
    ).where(DeploymentBooking.status.in_(DEPLOYMENT_OUTCOME_STATUSES))
    rows = db.execute(stmt.order_by(DeploymentBooking.deployment_date.asc(), DeploymentBooking.id.asc())).all()

    deployment_dates = [row.deployment_date for row in rows]
    total = len(deployment_dates)
    span_days = max((end - start).days, 1)
    average_per_week = round(total / (span_days / 7), 2)
    average_per_month = round(total / (span_days / 30.4375), 2)

    average_gap_days = None
    if total >= 2:
        gaps = [
            (deployment_dates[index] - deployment_dates[index - 1]).days
            for index in range(1, total)
        ]
        average_gap_days = round(sum(gaps) / len(gaps), 2)

    by_status = Counter(row.status for row in rows)
    return {
        "tenant": resolved_tenant.name if resolved_tenant else None,
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "period_days": span_days,
        "total": total,
        "average_per_week": average_per_week,
        "average_per_month": average_per_month,
        "average_gap_days": average_gap_days,
        "first_deployment": deployment_dates[0].isoformat() if deployment_dates else None,
        "last_deployment": deployment_dates[-1].isoformat() if deployment_dates else None,
        "by_status": dict(sorted(by_status.items())),
        "included_statuses": list(DEPLOYMENT_OUTCOME_STATUSES),
    }


def deployment_summary(
    db: Session,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    tenant: str | None = None,
    schedule_status: str | None = None,
    is_emergency: bool | None = None,
) -> dict[str, Any]:
    """Summarise deployments by status and tenant for a date range."""
    resolved_tenant = _resolve_tenant(db, tenant)
    stmt = select(
        DeploymentBooking.tenant_name,
        DeploymentBooking.status,
        DeploymentBooking.is_emergency,
        func.count().label("quantity"),
    ).group_by(DeploymentBooking.tenant_name, DeploymentBooking.status, DeploymentBooking.is_emergency)
    stmt = _apply_filters(
        stmt,
        tenant=resolved_tenant,
        date_from=date_from,
        date_to=date_to,
        schedule_status=_normalise_status(schedule_status),
        is_emergency=is_emergency,
    )
    rows = db.execute(stmt).all()
    by_status, by_tenant = Counter(), Counter()
    for row in rows:
        by_status[row.status] += row.quantity
        by_tenant[row.tenant_name] += row.quantity
    total = sum(row.quantity for row in rows)
    emergency_count = sum(row.quantity for row in rows if row.is_emergency)
    return {
        "tenant": resolved_tenant.name if resolved_tenant else None,
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "total": total,
        "normal": total - emergency_count,
        "emergency": emergency_count,
        "by_status": dict(sorted(by_status.items())),
        "by_tenant": dict(sorted(by_tenant.items())),
    }


def tenant_summary(
    db: Session,
    *,
    tenant: str,
    date_from: date | None = None,
    date_to: date | None = None,
    schedule_status: str | None = None,
    is_emergency: bool | None = None,
) -> dict[str, Any]:
    """Return an operational summary for one tenant."""
    resolved_tenant = _resolve_tenant(db, tenant)
    assert resolved_tenant is not None
    base = deployment_summary(
        db,
        date_from=date_from,
        date_to=date_to,
        tenant=resolved_tenant.name,
        schedule_status=schedule_status,
        is_emergency=is_emergency,
    )

    rm_stmt = (
        select(BookingAssignment)
        .join(DeploymentBooking, BookingAssignment.booking_id == DeploymentBooking.id)
        .options(selectinload(BookingAssignment.user))
        .where(DeploymentBooking.tenant_id == resolved_tenant.id)
    )
    _validate_dates(date_from, date_to)
    if date_from is not None:
        rm_stmt = rm_stmt.where(DeploymentBooking.deployment_date >= date_from)
    if date_to is not None:
        rm_stmt = rm_stmt.where(DeploymentBooking.deployment_date <= date_to)
    if schedule_status is not None:
        rm_stmt = rm_stmt.where(DeploymentBooking.status == _normalise_status(schedule_status))
    if is_emergency is not None:
        rm_stmt = rm_stmt.where(DeploymentBooking.is_emergency.is_(is_emergency))
    rm_rows = db.scalars(rm_stmt).all()
    rm_counts = Counter(assignment.user.full_name for assignment in rm_rows)

    base.update(
        {
            "tenant_id": resolved_tenant.id,
            "tenant_code": resolved_tenant.tenant_code,
            "release_manager_assignments": dict(sorted(rm_counts.items())),
        }
    )
    return base


def list_tenants(db: Session, *, active_only: bool = True, inactive_only: bool = False) -> dict[str, Any]:
    """Return configured tenants without exposing administrative secrets."""
    if active_only and inactive_only:
        raise HTTPException(422, "Choose active or inactive tenants, not both.")
    stmt = select(Tenant)
    if inactive_only:
        stmt = stmt.where(Tenant.is_active.is_(False))
    if active_only:
        stmt = stmt.where(Tenant.is_active.is_(True))
    rows = db.scalars(stmt.order_by(Tenant.name.asc())).all()
    return {
        "active_only": active_only,
        "inactive_only": inactive_only,
        "total": len(rows),
        "tenants": [
            {
                "id": row.id,
                "name": row.name,
                "tenant_code": row.tenant_code,
                "is_active": row.is_active,
            }
            for row in rows
        ],
    }
