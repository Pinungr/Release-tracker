"""Authenticated, read-only endpoints intended for AI/assistant clients."""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import settings
from ..security import UserPrincipal, require_ai_user, require_user
from ..services import ai_access_service, assistant_service, availability_service, pds_chat_service, pds_query_plan

router = APIRouter(prefix="/assistant", tags=["assistant"])


class ChatHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    query_scope: pds_query_plan.Plan | None = None
    content: str = Field(min_length=1, max_length=pds_chat_service.MAX_CHAT_MESSAGE_CHARS)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=pds_chat_service.MAX_CHAT_MESSAGE_CHARS)
    history: list[ChatHistoryItem] = Field(default_factory=list, max_length=pds_chat_service.MAX_CHAT_HISTORY)


@router.get("/access")
def assistant_access(
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_user),
):
    decision = ai_access_service.evaluate_user(db, user.user_id)
    return {
        "master_enabled": ai_access_service.master_ai_enabled(db),
        "allowed": decision.allowed,
        "reason": decision.reason,
        "source": decision.source,
        "chat_configured": pds_chat_service.chat_is_configured(),
        "intelligence_configured": pds_chat_service.intelligence_is_configured(),
        "provider": pds_chat_service._active_provider(),
        "provider_label": pds_chat_service.provider_label(),
        "model": pds_chat_service.active_model(),
        "read_only": True,
    }


@router.post("/chat")
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    _: UserPrincipal = Depends(require_ai_user),
):
    return pds_chat_service.ask_pds_ai(
        db,
        message=payload.message,
        history=[item.model_dump() for item in payload.history],
    )


@router.get("/schedules/{schedule_no}")
def get_schedule(
    schedule_no: str,
    db: Session = Depends(get_db),
    _: UserPrincipal = Depends(require_ai_user),
):
    return assistant_service.get_schedule(db, schedule_no)


@router.get("/availability/next-slot")
def next_available_slot(
    db: Session = Depends(get_db),
    _: UserPrincipal = Depends(require_ai_user),
):
    return availability_service.next_available_slot(db)


@router.get("/schedules")
def search_schedules(
    tenant: str | None = Query(default=None, max_length=120),
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = Query(default=None, max_length=40),
    is_emergency: bool | None = None,
    change_number: str | None = Query(default=None, max_length=64),
    schedule_no: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=25, ge=1, le=assistant_service.MAX_ASSISTANT_RESULTS),
    db: Session = Depends(get_db),
    _: UserPrincipal = Depends(require_ai_user),
):
    return assistant_service.search_schedules(
        db,
        tenant=tenant,
        date_from=date_from,
        date_to=date_to,
        schedule_status=status,
        is_emergency=is_emergency,
        change_number=change_number,
        schedule_no=schedule_no,
        limit=limit,
    )


@router.get("/users/count")
def count_users(
    group: str | None = Query(default=None, max_length=120),
    active_only: bool = False,
    db: Session = Depends(get_db),
    _: UserPrincipal = Depends(require_ai_user),
):
    return assistant_service.count_users(db, group=group, active_only=active_only)


@router.get("/count")
def count_schedules(
    tenant: str | None = Query(default=None, max_length=120),
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = Query(default=None, max_length=40),
    is_emergency: bool | None = None,
    db: Session = Depends(get_db),
    _: UserPrincipal = Depends(require_ai_user),
):
    return assistant_service.count_schedules(
        db,
        tenant=tenant,
        date_from=date_from,
        date_to=date_to,
        schedule_status=status,
        is_emergency=is_emergency,
    )


@router.get("/tenants")
def list_tenants(
    active_only: bool = True,
    inactive_only: bool = False,
    db: Session = Depends(get_db),
    _: UserPrincipal = Depends(require_ai_user),
):
    return assistant_service.list_tenants(db, active_only=active_only, inactive_only=inactive_only)


@router.get("/deployment-summary")
def deployment_summary(
    date_from: date | None = None,
    date_to: date | None = None,
    tenant: str | None = Query(default=None, max_length=120),
    status: str | None = Query(default=None, max_length=40),
    is_emergency: bool | None = None,
    db: Session = Depends(get_db),
    _: UserPrincipal = Depends(require_ai_user),
):
    return assistant_service.deployment_summary(
        db,
        schedule_status=status,
        is_emergency=is_emergency,        date_from=date_from,
        date_to=date_to,
        tenant=tenant,
    )


@router.get("/tenant-summary/{tenant}")
def tenant_summary(
    tenant: str,
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = Query(default=None, max_length=40),
    is_emergency: bool | None = None,
    db: Session = Depends(get_db),
    _: UserPrincipal = Depends(require_ai_user),
):
    return assistant_service.tenant_summary(
        db,
        schedule_status=status,
        is_emergency=is_emergency,        tenant=tenant,
        date_from=date_from,
        date_to=date_to,
    )
