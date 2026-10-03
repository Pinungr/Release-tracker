"""Read-only MCP server for Copilot, Codex, ChatGPT, Claude and other MCP hosts.

This module intentionally exposes only query tools.  It shares the exact same
assistant_service functions as the authenticated REST API, so there is no
second implementation of PDS query logic and no model-generated SQL.
"""
from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .database import SessionLocal
from .services import ai_access_service, assistant_service

mcp = MCPServer("PDS Read-only Assistant")


def _call(fn, *args, **kwargs):
    """Preserve useful PDS validation/not-found messages for MCP clients."""
    try:
        return fn(*args, **kwargs)
    except HTTPException as exc:
        raise ToolError(str(exc.detail)) from exc




def _require_requester(db, requester: str):
    """Resolve the PDS user supplied by the trusted POC connector.

    In shared-key mode the MCP key identifies the connector, not the employee.
    The connector must therefore bind this value from its authenticated user
    context; it must never let prompt text choose another employee. Future
    Entra delegated authentication replaces this hand-off.
    """
    user = ai_access_service.user_by_username_or_email(db, requester)
    if user is None or not user.is_active:
        raise ToolError("Unknown or inactive PDS requester.")
    decision = ai_access_service.evaluate_user(db, user.id)
    if not decision.allowed:
        raise ToolError(decision.reason)
    return user


def _date(value: str | None, field: str) -> date | None:
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ToolError(f"{field} must be YYYY-MM-DD.") from exc


@mcp.tool()
def get_schedule(schedule_no: str, requester: str) -> dict:
    """Get one PDS schedule. requester must be the authenticated PDS username/email supplied by the trusted host."""
    with SessionLocal() as db:
        _require_requester(db, requester)
        return _call(assistant_service.get_schedule, db, schedule_no)


@mcp.tool()
def search_schedules(
    requester: str,
    tenant: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    status: str | None = None,
    change_number: str | None = None,
    schedule_no: str | None = None,
    limit: int = 25,
) -> list[dict]:
    """Search PDS schedules. requester must be bound to the authenticated PDS user by the trusted host."""
    with SessionLocal() as db:
        _require_requester(db, requester)
        return _call(
            assistant_service.search_schedules,
            db,
            tenant=tenant,
            date_from=_date(date_from, "date_from"),
            date_to=_date(date_to, "date_to"),
            schedule_status=status,
            change_number=change_number,
            schedule_no=schedule_no,
            limit=limit,
        )


@mcp.tool()
def count_schedules(
    requester: str,
    tenant: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    status: str | None = None,
) -> dict:
    """Count PDS schedules. requester must be bound to the authenticated PDS user by the trusted host."""
    with SessionLocal() as db:
        _require_requester(db, requester)
        return _call(
            assistant_service.count_schedules,
            db,
            tenant=tenant,
            date_from=_date(date_from, "date_from"),
            date_to=_date(date_to, "date_to"),
            schedule_status=status,
        )


@mcp.tool()
def get_deployment_summary(
    requester: str,
    date_from: str | None = None,
    date_to: str | None = None,
    tenant: str | None = None,
) -> dict:
    """Summarise deployments. requester must be bound to the authenticated PDS user by the trusted host."""
    with SessionLocal() as db:
        _require_requester(db, requester)
        return _call(
            assistant_service.deployment_summary,
            db,
            date_from=_date(date_from, "date_from"),
            date_to=_date(date_to, "date_to"),
            tenant=tenant,
        )


@mcp.tool()
def list_tenants(requester: str, active_only: bool = True) -> dict:
    """List configured PDS tenants. requester must be bound to the authenticated PDS user by the trusted host."""
    with SessionLocal() as db:
        _require_requester(db, requester)
        return _call(assistant_service.list_tenants, db, active_only=active_only)


@mcp.tool()
def get_tenant_summary(
    requester: str,
    tenant: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """Summarise one tenant. requester must be bound to the authenticated PDS user by the trusted host."""
    with SessionLocal() as db:
        _require_requester(db, requester)
        return _call(
            assistant_service.tenant_summary,
            db,
            tenant=tenant,
            date_from=_date(date_from, "date_from"),
            date_to=_date(date_to, "date_to"),
        )


# streamable_http_path='/' makes the FastAPI mount point itself the endpoint,
# e.g. mounting this app at /mcp gives clients https://host/mcp.
mcp_app = mcp.streamable_http_app(
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)
