"""Read-only PDS assistant with a zero-dependency built-in query mode.

The default ``builtin`` provider does not use an LLM at all.  It recognises a
small, explicit set of PDS question patterns and calls only the allow-listed
functions in :mod:`assistant_service`.  This keeps the local POC fast and
predictable while preserving the same chat UI, access controls and tool layer.

When an organisation later provides an approved Responses-compatible AI
gateway, set ``AI_PROVIDER=org_gateway`` (or another non-builtin value) and
supply the generic ``AI_*`` environment variables.  No UI or database-query
code needs to change.
"""
from __future__ import annotations

import calendar
import json
import re
from datetime import date, timedelta
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from ..utils.dates import today_local
from . import assistant_service

MAX_CHAT_HISTORY = 10
MAX_CHAT_MESSAGE_CHARS = 4000
MAX_TOOL_ROUNDS = 4

_BUILTIN_PROVIDER_NAMES = {"builtin", "built_in", "rules", "rule_based", "local_rules"}
_MONTHS = {
    name.lower(): index
    for index, name in enumerate(calendar.month_name)
    if name
}
_MONTHS.update(
    {
        name.lower(): index
        for index, name in enumerate(calendar.month_abbr)
        if name
    }
)


def _date_or_none(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"Invalid ISO date '{value}'.") from exc


def _tool_definitions() -> list[dict[str, Any]]:
    """Responses-compatible definitions for a future organisation gateway."""
    nullable_string = {"type": ["string", "null"]}
    return [
        {
            "type": "function",
            "name": "get_schedule",
            "description": "Get one PDS schedule by schedule number, including Change No. and assigned Release Manager(s).",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {"schedule_no": {"type": "string"}},
                "required": ["schedule_no"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "search_schedules",
            "description": "Search PDS schedules using approved read-only filters.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "tenant": nullable_string,
                    "date_from": nullable_string,
                    "date_to": nullable_string,
                    "status": nullable_string,
                    "change_number": nullable_string,
                    "schedule_no": nullable_string,
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["tenant", "date_from", "date_to", "status", "change_number", "schedule_no", "limit"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "count_schedules",
            "description": "Count PDS schedules/releases/deployments for an optional tenant/date/status filter.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "tenant": nullable_string,
                    "date_from": nullable_string,
                    "date_to": nullable_string,
                    "status": nullable_string,
                },
                "required": ["tenant", "date_from", "date_to", "status"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "deployment_summary",
            "description": "Summarize PDS deployments by status and tenant for a date range.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "tenant": nullable_string,
                    "date_from": nullable_string,
                    "date_to": nullable_string,
                },
                "required": ["tenant", "date_from", "date_to"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "tenant_summary",
            "description": "Return an operational summary for one tenant, including Release Manager assignment counts.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "tenant": {"type": "string"},
                    "date_from": nullable_string,
                    "date_to": nullable_string,
                },
                "required": ["tenant", "date_from", "date_to"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "list_tenants",
            "description": "List configured PDS tenants and return the tenant count.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {"active_only": {"type": "boolean"}},
                "required": ["active_only"],
                "additionalProperties": False,
            },
        },
    ]


def _instructions() -> str:
    today = today_local().isoformat()
    return f"""You are PDS AI, the read-only assistant for Production Deployment Scheduler.
Today is {today}. PDS operational timezone is {settings.timezone}.

Rules:
- Answer questions about PDS schedules, releases, deployments, Change Nos., tenants, statuses, dates, emergency changes, and assigned Release Managers.
- For factual PDS-data answers, use only the supplied read-only tools. Never invent values.
- Never write data or claim to cancel/reschedule/assign/update anything.
- Do not generate SQL and do not ask for database credentials.
- Keep answers concise and practical.
"""


def _dispatch_tool(db: Session, name: str, arguments: dict[str, Any]) -> Any:
    if name == "get_schedule":
        return assistant_service.get_schedule(db, str(arguments.get("schedule_no") or ""))
    if name == "search_schedules":
        return assistant_service.search_schedules(
            db,
            tenant=arguments.get("tenant"),
            date_from=_date_or_none(arguments.get("date_from")),
            date_to=_date_or_none(arguments.get("date_to")),
            schedule_status=arguments.get("status"),
            change_number=arguments.get("change_number"),
            schedule_no=arguments.get("schedule_no"),
            limit=int(arguments.get("limit") or 25),
        )
    if name == "count_schedules":
        return assistant_service.count_schedules(
            db,
            tenant=arguments.get("tenant"),
            date_from=_date_or_none(arguments.get("date_from")),
            date_to=_date_or_none(arguments.get("date_to")),
            schedule_status=arguments.get("status"),
        )
    if name == "deployment_summary":
        return assistant_service.deployment_summary(
            db,
            tenant=arguments.get("tenant"),
            date_from=_date_or_none(arguments.get("date_from")),
            date_to=_date_or_none(arguments.get("date_to")),
        )
    if name == "tenant_summary":
        return assistant_service.tenant_summary(
            db,
            tenant=str(arguments.get("tenant") or ""),
            date_from=_date_or_none(arguments.get("date_from")),
            date_to=_date_or_none(arguments.get("date_to")),
        )
    if name == "list_tenants":
        return assistant_service.list_tenants(db, active_only=bool(arguments.get("active_only", True)))
    raise ValueError(f"Unsupported tool '{name}'.")


def _active_provider() -> str:
    value = (settings.ai_provider or "builtin").strip().lower().replace("-", "_")
    return value or "builtin"


def _is_builtin_provider() -> bool:
    return _active_provider() in _BUILTIN_PROVIDER_NAMES


def provider_label() -> str:
    provider = _active_provider()
    if provider in _BUILTIN_PROVIDER_NAMES:
        return "Built-in PDS"
    labels = {
        "openai": "OpenAI",
        "claude": "Claude",
        "azure_openai": "Azure OpenAI",
        "org_gateway": "Org AI",
        "gateway": "Org AI",
    }
    return labels.get(provider, "Org AI")


def active_model() -> str:
    return "Rule-based" if _is_builtin_provider() else settings.ai_model


def chat_is_configured() -> bool:
    if _is_builtin_provider():
        return True
    return bool(settings.ai_api_key.strip() and settings.ai_base_url.strip() and settings.ai_model.strip())


def _extract_text(response: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in response.get("output") or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    return "\n".join(chunk.strip() for chunk in chunks if chunk.strip()).strip()


def _function_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in (response.get("output") or []) if item.get("type") == "function_call"]


def _post_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Call a Responses-compatible organisation/hosted AI gateway."""
    if not settings.ai_api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PDS AI is configured for an external gateway, but AI_API_KEY is not configured on the backend.",
        )
    url = f"{settings.ai_base_url.rstrip('/')}/{settings.ai_api_path.lstrip('/')}"
    headers = {"Content-Type": "application/json"}
    auth_value = f"{settings.ai_auth_scheme.strip()} {settings.ai_api_key.strip()}".strip()
    if settings.ai_auth_header.strip():
        headers[settings.ai_auth_header.strip()] = auth_value
    try:
        with httpx.Client(timeout=settings.ai_timeout_seconds) as client:
            response = client.post(url, headers=headers, json=payload)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PDS could not reach the configured organisation AI gateway.",
        ) from exc

    if response.status_code >= 400:
        provider_detail = ""
        try:
            body = response.json()
            provider_detail = str((body.get("error") or {}).get("message") or "").strip()
        except (ValueError, AttributeError):
            provider_detail = ""
        suffix = f" {provider_detail[:300]}" if provider_detail else ""
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI gateway request failed.{suffix}".strip(),
        )
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The configured AI gateway returned an invalid response.",
        ) from exc


def _run_tool(db: Session, name: str, arguments: Any) -> dict[str, Any]:
    try:
        if isinstance(arguments, str):
            parsed = json.loads(arguments or "{}")
        elif isinstance(arguments, dict):
            parsed = arguments
        else:
            parsed = dict(arguments or {})
        result = _dispatch_tool(db, name, parsed)
        return {"ok": True, "result": result}
    except HTTPException as exc:
        return {"ok": False, "error": str(exc.detail)}
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc)}


def _clean_history(history: list[dict[str, str]] | None) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for item in (history or [])[-MAX_CHAT_HISTORY:]:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        items.append({"role": role, "content": content[:MAX_CHAT_MESSAGE_CHARS]})
    return items


def _ask_via_responses(db: Session, clean_message: str, history: list[dict[str, str]] | None) -> dict[str, Any]:
    input_items: list[dict[str, str]] = _clean_history(history)
    input_items.append({"role": "user", "content": clean_message})

    common = {
        "model": settings.ai_model,
        "instructions": _instructions(),
        "tools": _tool_definitions(),
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "max_output_tokens": 700,
        "store": False,
    }
    conversation_items: list[dict[str, Any]] = list(input_items)
    response = _post_response({**common, "input": conversation_items})

    for _ in range(MAX_TOOL_ROUNDS):
        calls = _function_calls(response)
        if not calls:
            text = _extract_text(response)
            if not text:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="PDS AI returned no answer.")
            return {
                "answer": text,
                "model": response.get("model") or settings.ai_model,
                "provider": _active_provider(),
                "read_only": True,
            }

        conversation_items.extend(response.get("output") or [])
        outputs: list[dict[str, str]] = []
        for call in calls:
            call_id = str(call.get("call_id") or "")
            name = str(call.get("name") or "")
            output = _run_tool(db, name, call.get("arguments") or "{}")
            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(output, default=str),
                }
            )
        conversation_items.extend(outputs)
        response = _post_response({**common, "input": conversation_items})

    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="PDS AI exceeded the maximum read-only tool steps for this question.",
    )


def _human_period(result: dict[str, Any]) -> str | None:
    start_raw = result.get("date_from")
    end_raw = result.get("date_to")
    try:
        start = date.fromisoformat(start_raw) if start_raw else None
        end = date.fromisoformat(end_raw) if end_raw else None
    except (TypeError, ValueError):
        return None
    if start and end and start.day == 1 and start.year == end.year and start.month == end.month:
        if end.day == calendar.monthrange(end.year, end.month)[1]:
            return start.strftime("%B %Y")
    if start and end:
        return f"{start.strftime('%d %b %Y')} to {end.strftime('%d %b %Y')}"
    if start:
        return f"from {start.strftime('%d %b %Y')}"
    return f"through {end.strftime('%d %b %Y')}" if end else None


def _question_noun(question: str, total: int) -> str:
    lower = question.lower()
    if "release" in lower:
        base = "release"
    elif "deployment" in lower or "deployed" in lower:
        base = "deployment"
    else:
        base = "schedule"
    return base if total == 1 else f"{base}s"


def _format_direct_tool_answer(name: str, output: dict[str, Any], question: str) -> str | None:
    if not output.get("ok"):
        error = str(output.get("error") or "The requested PDS data could not be retrieved.").strip()
        return error or None
    result = output.get("result")

    if name == "count_schedules" and isinstance(result, dict):
        lower = question.lower()
        if "emergency" in lower:
            total = int(result.get("emergency") or 0)
            noun = _question_noun(question, total)
            period = _human_period(result)
            tenant = result.get("tenant")
            subject = f"{tenant} " if tenant else ""
            suffix = f" in {period}" if period else ""
            return f"{total} emergency {subject}{noun} occurred{suffix}.".replace("  ", " ").strip()
        if re.search(r"\bnormal\b", lower):
            total = int(result.get("normal") or 0)
            noun = _question_noun(question, total)
            period = _human_period(result)
            tenant = result.get("tenant")
            subject = f"{tenant} " if tenant else ""
            suffix = f" in {period}" if period else ""
            return f"{total} normal {subject}{noun} occurred{suffix}.".replace("  ", " ").strip()

        total = int(result.get("total") or 0)
        noun = _question_noun(question, total)
        period = _human_period(result)
        tenant = result.get("tenant")
        status_filter = result.get("status_filter")
        subject = f"{tenant} " if tenant else ""
        status_text = f" {str(status_filter).replace('_', ' ').lower()}" if status_filter else ""
        if period:
            return f"{total} {subject}{status_text} {noun} occurred in {period}.".replace("  ", " ").strip()
        return f"There are {total} {subject}{status_text} {noun}.".replace("  ", " ").strip()

    if name == "list_tenants" and isinstance(result, dict):
        total = int(result.get("total") or 0)
        tenants = [str(item.get("name") or item.get("tenant_code") or "").strip() for item in result.get("tenants") or []]
        tenants = [item for item in tenants if item]
        if tenants:
            label = "tenant is" if total == 1 else "tenants are"
            return f"{total} {label} configured: {', '.join(tenants)}."
        return "No tenants are currently configured."

    if name == "get_schedule" and isinstance(result, dict):
        schedule_no = str(result.get("schedule_no") or "Schedule")
        display_schedule_no = schedule_no.upper() if schedule_no.lower().startswith("pds-") else schedule_no
        status_value = str(result.get("status") or "unknown").replace("_", " ").lower()
        tenant = str(result.get("tenant") or "").strip()
        day = str(result.get("deployment_date") or "").strip()
        change = str(result.get("change_number") or "").strip()
        managers = [str(item.get("full_name") or "").strip() for item in result.get("release_managers") or []]
        managers = [item for item in managers if item]

        question_lower = question.lower()
        asks_for_rm = (
            "release manager" in question_lower
            or bool(re.search(r"\brm\b", question_lower))
            or "who is assigned" in question_lower
            or "who was assigned" in question_lower
        )
        if asks_for_rm:
            if managers:
                label = "Release Manager" if len(managers) == 1 else "Release Managers"
                return f"The {label} for {display_schedule_no} {'is' if len(managers) == 1 else 'are'} {', '.join(managers)}."
            return f"No Release Manager is currently assigned to {display_schedule_no}."

        asks_for_change = (
            "change number" in question_lower
            or "change no" in question_lower
            or bool(re.search(r"\bchg\b", question_lower))
        )
        if asks_for_change:
            if change:
                return f"The Change No. for {display_schedule_no} is {change}."
            return f"No Change No. is currently assigned to {display_schedule_no}."

        if "status" in question_lower:
            return f"{display_schedule_no} is currently {status_value}."

        parts = [f"{display_schedule_no} is {status_value}"]
        if tenant:
            parts.append(f"for {tenant}")
        if day:
            parts.append(f"on {day}")
        sentence = " ".join(parts) + "."
        extras = []
        if change:
            extras.append(f"Change No.: {change}")
        if managers:
            extras.append(f"RM: {', '.join(managers)}")
        return sentence + (" " + ". ".join(extras) + "." if extras else "")

    if name == "search_schedules" and isinstance(result, list):
        if not result:
            return "No matching PDS schedules were found."
        lines = []
        for item in result[:10]:
            ref = item.get("schedule_no") or "Schedule"
            tenant = item.get("tenant") or ""
            day = item.get("deployment_date") or ""
            status_value = str(item.get("status") or "").replace("_", " ")
            change = item.get("change_number") or ""
            extra = f" | {change}" if change else ""
            lines.append(f"- {ref} | {tenant} | {day} | {status_value}{extra}")
        suffix = f"\nShowing 10 of {len(result)} matches." if len(result) > 10 else ""
        return f"Found {len(result)} matching schedules:\n" + "\n".join(lines) + suffix

    if name in {"deployment_summary", "tenant_summary"} and isinstance(result, dict):
        total = int(result.get("total") or 0)
        period = _human_period(result)
        tenant = str(result.get("tenant") or "").strip()
        noun = _question_noun(question, total)
        lead = f"{total} {tenant + ' ' if tenant else ''}{noun}"
        if period:
            lead += f" occurred in {period}"
        by_status = result.get("by_status") or {}
        parts = [lead + "."]
        if by_status:
            breakdown = ", ".join(f"{str(k).replace('_', ' ').title()}: {v}" for k, v in by_status.items())
            parts.append(f"Status: {breakdown}.")
        rm_counts = result.get("release_manager_assignments") or {}
        if rm_counts and ("release manager" in question.lower() or re.search(r"\brm\b", question.lower())):
            managers = ", ".join(f"{name}: {count}" for name, count in rm_counts.items())
            parts.append(f"RM assignments: {managers}.")
        return " ".join(parts)

    return None


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _extract_period(question: str) -> tuple[date | None, date | None]:
    lower = question.lower()
    today = today_local()

    iso_dates = [date.fromisoformat(value) for value in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", question)]
    if len(iso_dates) >= 2:
        first, second = iso_dates[0], iso_dates[1]
        return (first, second) if first <= second else (second, first)
    if len(iso_dates) == 1:
        return iso_dates[0], iso_dates[0]

    if "today" in lower:
        return today, today
    if "yesterday" in lower:
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    if "this month" in lower:
        return _month_bounds(today.year, today.month)
    if "last month" in lower or "previous month" in lower:
        month = today.month - 1
        year = today.year
        if month == 0:
            month = 12
            year -= 1
        return _month_bounds(year, month)
    if "upcoming" in lower or "future" in lower:
        return today, None
    if "this week" in lower:
        # PDS operational week is Sunday through Saturday for query purposes;
        # booking rules still decide which days are actually bookable.
        start = today - timedelta(days=(today.weekday() + 1) % 7)
        return start, start + timedelta(days=6)
    if "next week" in lower:
        start = today - timedelta(days=(today.weekday() + 1) % 7) + timedelta(days=7)
        return start, start + timedelta(days=6)
    next_days = re.search(r"\bnext\s+(\d{1,3})\s+days?\b", lower)
    if next_days:
        return today, today + timedelta(days=int(next_days.group(1)))
    if "this year" in lower:
        return date(today.year, 1, 1), date(today.year, 12, 31)
    if "last year" in lower or "previous year" in lower:
        year = today.year - 1
        return date(year, 1, 1), date(year, 12, 31)

    month_pattern = "|".join(sorted((re.escape(name) for name in _MONTHS), key=len, reverse=True))
    match = re.search(rf"\b({month_pattern})\b(?:\s+(20\d{{2}}))?", lower)
    if match:
        month = _MONTHS[match.group(1)]
        year = int(match.group(2)) if match.group(2) else today.year
        return _month_bounds(year, month)

    year_match = re.search(r"\b(20\d{2})\b", lower)
    if year_match:
        year = int(year_match.group(1))
        return date(year, 1, 1), date(year, 12, 31)

    return None, None


def _extract_status(question: str) -> str | None:
    lower = question.lower()
    aliases = [
        ("validation pending", "VALIDATION_PENDING"),
        ("in progress", "IN_PROGRESS"),
        ("rolled back", "ROLLED_BACK"),
        ("rollback", "ROLLED_BACK"),
        ("successful", "SUCCESSFUL"),
        ("success", "SUCCESSFUL"),
        ("completed", "COMPLETED"),
        ("complete", "COMPLETED"),
        ("cancelled", "CANCELLED"),
        ("canceled", "CANCELLED"),
        ("failed", "FAILED"),
        ("failure", "FAILED"),
        ("booked", "BOOKED"),
        ("locked", "LOCKED"),
    ]
    for phrase, value in aliases:
        if phrase in lower:
            return value
    return None


def _extract_schedule_no(question: str) -> str | None:
    match = re.search(r"\bpds[\s_-]*(\d+)\b", question, re.IGNORECASE)
    if not match:
        return None
    return f"pds-{match.group(1)}"


def _extract_change_no(question: str) -> str | None:
    match = re.search(r"\b(?:chg|crq)[-_ ]?[a-z0-9]+\b", question, re.IGNORECASE)
    return match.group(0).replace(" ", "") if match else None


def _extract_tenant(db: Session, question: str) -> str | None:
    lower = question.lower()
    data = assistant_service.list_tenants(db, active_only=False)
    candidates: list[tuple[str, str]] = []
    for item in data.get("tenants") or []:
        name = str(item.get("name") or "").strip()
        code = str(item.get("tenant_code") or "").strip()
        canonical = name or code
        if name:
            candidates.append((name, canonical))
        if code and code.lower() != name.lower():
            candidates.append((code, canonical))
    for token, canonical in sorted(candidates, key=lambda pair: len(pair[0]), reverse=True):
        token_lower = token.lower()
        if re.search(rf"(?<![a-z0-9]){re.escape(token_lower)}(?![a-z0-9])", lower):
            return canonical
    return None


def _builtin_help() -> str:
    return (
        "I can answer read-only PDS questions without an external AI service. Try: "
        "'How many NCAP releases happened in September?', "
        "'Show failed RADA deployments last month', "
        "'Who is the RM for PDS-001?', "
        "'What is the Change No. for PDS-001?', or "
        "'How many tenants are configured?'."
    )


def _ask_via_builtin(db: Session, clean_message: str) -> dict[str, Any]:
    lower = clean_message.lower().strip()

    if re.search(r"\b(cancel|reschedule|assign|unassign|delete|create|book|update|modify|close|start|freeze|unfreeze)\b", lower):
        answer = "PDS Assistant is read-only. Use the normal PDS screens to make changes; I can only look up and summarize PDS data."
        return {"answer": answer, "model": "Rule-based", "provider": "builtin", "read_only": True}

    if lower in {"hi", "hello", "hey", "help", "what can you do", "what can you do?"} or "what can i ask" in lower:
        return {"answer": _builtin_help(), "model": "Rule-based", "provider": "builtin", "read_only": True}

    schedule_no = _extract_schedule_no(clean_message)
    if schedule_no:
        output = _run_tool(db, "get_schedule", {"schedule_no": schedule_no})
        answer = _format_direct_tool_answer("get_schedule", output, clean_message)
        return {"answer": answer or _builtin_help(), "model": "Rule-based", "provider": "builtin", "read_only": True}

    change_no = _extract_change_no(clean_message)
    if change_no and any(term in lower for term in ("schedule", "release", "deployment", "change", "crq")):
        output = _run_tool(
            db,
            "search_schedules",
            {"change_number": change_no, "tenant": None, "date_from": None, "date_to": None, "status": None, "schedule_no": None, "limit": 25},
        )
        answer = _format_direct_tool_answer("search_schedules", output, clean_message)
        return {"answer": answer or _builtin_help(), "model": "Rule-based", "provider": "builtin", "read_only": True}

    if "tenant" in lower and any(term in lower for term in ("how many", "count", "list", "show", "configured", "available")):
        output = _run_tool(db, "list_tenants", {"active_only": True})
        answer = _format_direct_tool_answer("list_tenants", output, clean_message)
        return {"answer": answer or _builtin_help(), "model": "Rule-based", "provider": "builtin", "read_only": True}

    tenant = _extract_tenant(db, clean_message)
    date_from, date_to = _extract_period(clean_message)
    schedule_status = _extract_status(clean_message)

    count_intent = bool(re.search(r"\b(how many|count|number of|total)\b", lower))
    list_intent = bool(re.search(r"\b(show|list|find|which|display|give me)\b", lower)) or "what are" in lower
    summary_intent = bool(re.search(r"\b(summary|summarize|summarise|breakdown|overview)\b", lower))
    pds_noun = bool(re.search(r"\b(schedule|schedules|release|releases|deployment|deployments|deployed|crq|changes?)\b", lower))

    if count_intent and pds_noun:
        output = _run_tool(
            db,
            "count_schedules",
            {"tenant": tenant, "date_from": date_from, "date_to": date_to, "status": schedule_status},
        )
        answer = _format_direct_tool_answer("count_schedules", output, clean_message)
        return {"answer": answer or _builtin_help(), "model": "Rule-based", "provider": "builtin", "read_only": True}

    if summary_intent and pds_noun:
        tool_name = "tenant_summary" if tenant else "deployment_summary"
        arguments = {"tenant": tenant, "date_from": date_from, "date_to": date_to}
        if tool_name == "deployment_summary":
            arguments["tenant"] = tenant
        output = _run_tool(db, tool_name, arguments)
        answer = _format_direct_tool_answer(tool_name, output, clean_message)
        return {"answer": answer or _builtin_help(), "model": "Rule-based", "provider": "builtin", "read_only": True}

    if list_intent and pds_noun:
        output = _run_tool(
            db,
            "search_schedules",
            {
                "tenant": tenant,
                "date_from": date_from,
                "date_to": date_to,
                "status": schedule_status,
                "change_number": None,
                "schedule_no": None,
                "limit": 25,
            },
        )
        answer = _format_direct_tool_answer("search_schedules", output, clean_message)
        return {"answer": answer or _builtin_help(), "model": "Rule-based", "provider": "builtin", "read_only": True}

    if tenant and pds_noun:
        output = _run_tool(
            db,
            "deployment_summary",
            {"tenant": tenant, "date_from": date_from, "date_to": date_to},
        )
        answer = _format_direct_tool_answer("deployment_summary", output, clean_message)
        return {"answer": answer or _builtin_help(), "model": "Rule-based", "provider": "builtin", "read_only": True}

    return {"answer": _builtin_help(), "model": "Rule-based", "provider": "builtin", "read_only": True}


def ask_pds_ai(
    db: Session,
    *,
    message: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    clean_message = (message or "").strip()
    if not clean_message:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "message is required.")
    if len(clean_message) > MAX_CHAT_MESSAGE_CHARS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "message is too long.")

    if _is_builtin_provider():
        return _ask_via_builtin(db, clean_message)
    return _ask_via_responses(db, clean_message, history)
