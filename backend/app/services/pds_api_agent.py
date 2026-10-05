"""Allow-listed, read-only backend API agent for PDS chat."""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from . import assistant_service, availability_service

API_OPERATIONS = frozenset(
    {
        "get_schedule",
        "search_schedules",
        "count_schedules",
        "deployment_summary",
        "deployment_frequency",
        "tenant_summary",
        "list_tenants",
        "next_available_slot",
        "count_users",
    }
)


def _date_or_none(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"Invalid ISO date '{value}'.") from exc


def execute(db: Session, operation: str, arguments: dict[str, Any]) -> Any:
    """Run an operation exposed by the authenticated read-only assistant API.

    This in-process adapter deliberately calls the same service functions as
    ``/api/assistant/*`` routes instead of making an HTTP request back into the
    current server. The chat endpoint has already authorized the user, and the
    API/service layer remains the sole source of PDS facts.
    """
    if operation == "count_users":
        return assistant_service.count_users(db, group=arguments.get("group"), active_only=bool(arguments.get("active_only", False)))
    if operation == "get_schedule":
        return assistant_service.get_schedule(
            db, str(arguments.get("schedule_no") or "")
        )
    extra_filters = {"is_emergency": arguments["is_emergency"]} if arguments.get("is_emergency") is not None else {}
    if operation == "search_schedules":
        return assistant_service.search_schedules(
            db,
            tenant=arguments.get("tenant"),
            date_from=_date_or_none(arguments.get("date_from")),
            date_to=_date_or_none(arguments.get("date_to")),
            schedule_status=arguments.get("status"),
            change_number=arguments.get("change_number"),
            schedule_no=arguments.get("schedule_no"),
            limit=int(arguments.get("limit") or 25),
            **extra_filters,
        )
    if operation == "count_schedules":
        return assistant_service.count_schedules(
            db,
            tenant=arguments.get("tenant"),
            date_from=_date_or_none(arguments.get("date_from")),
            date_to=_date_or_none(arguments.get("date_to")),
            schedule_status=arguments.get("status"),
            **extra_filters,
        )
    if operation == "deployment_summary":
        return assistant_service.deployment_summary(
            db,
            tenant=arguments.get("tenant"),
            date_from=_date_or_none(arguments.get("date_from")),
            date_to=_date_or_none(arguments.get("date_to")),
            schedule_status=arguments.get("status"),
            **extra_filters,
        )
    if operation == "deployment_frequency":
        return assistant_service.deployment_frequency(
            db,
            tenant=arguments.get("tenant"),
            date_from=_date_or_none(arguments.get("date_from")),
            date_to=_date_or_none(arguments.get("date_to")),
            **extra_filters,
        )
    if operation == "tenant_summary":
        return assistant_service.tenant_summary(
            db,
            tenant=str(arguments.get("tenant") or ""),
            date_from=_date_or_none(arguments.get("date_from")),
            date_to=_date_or_none(arguments.get("date_to")),
            schedule_status=arguments.get("status"),
            **extra_filters,
        )
    if operation == "list_tenants":
        return assistant_service.list_tenants(
            db, active_only=bool(arguments.get("active_only", True)), inactive_only=bool(arguments.get("inactive_only", False))
        )
    if operation == "next_available_slot":
        return availability_service.next_available_slot(db)
    raise ValueError(f"Unsupported backend API operation '{operation}'.")


def handle_tool_call(
    db: Session,
    operation: str,
    arguments: Any,
) -> dict[str, Any]:
    """Normalize a model tool call and return an explicit success/error result."""
    try:
        if isinstance(arguments, str):
            parsed = json.loads(arguments or "{}")
        elif isinstance(arguments, dict):
            parsed = arguments
        else:
            parsed = dict(arguments or {})
        if not isinstance(parsed, dict):
            return {"ok": False, "error": "Tool arguments must be a JSON object."}
        for key in ("active_only", "inactive_only", "is_emergency"):
            if key in parsed and parsed[key] is not None and not isinstance(parsed[key], bool):
                return {"ok": False, "error": f"'{key}' must be a boolean, not text."}
        for key in ("tenant", "group", "status", "schedule_no", "change_number"):
            if parsed.get(key) is not None and not isinstance(parsed[key], str):
                return {"ok": False, "error": f"'{key}' must be text."}
        result = execute(db, operation, parsed)
        if result is None:
            return {"ok": False, "error": "The backend API returned no result; try another read-only lookup."}
        return {"ok": True, "result": result}
    except HTTPException as exc:
        return {"ok": False, "error": str(exc.detail)}
    except SQLAlchemyError:
        db.rollback()
        return {"ok": False, "error": "The read-only database lookup failed. Retry with another supported lookup."}
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
