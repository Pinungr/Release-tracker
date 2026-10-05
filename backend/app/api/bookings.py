"""Authenticated booking endpoints."""
from __future__ import annotations

from datetime import date, datetime
import json
from sqlalchemy import func, select
from pydantic import BaseModel, Field, field_validator
from ..schemas.booking import AuditEventOut, ScheduleListItem, TenantUpcoming

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session
from pydantic import ValidationError as PydanticValidationError
from fastapi.exceptions import RequestValidationError

from ..database import get_db
from ..models import AccessGroup, DeploymentBooking, BookingAudit, BookingCollaborator, GroupMembership, GroupType, User
from ..schemas import (
    BookingCancel,
    BookingCreate,
    BookingCreated,
    BookingDetail,
    BookingSummary,
    BookingUpdate,
    CollaboratorsUpdate,
    RescheduleRequest,
    SlotOptionOut,
    StartWorkRequest,
)
from ..security import AdminPrincipal, UserPrincipal, require_user
from ..security.ratelimit import enforce
from ..services import attachment_service, booking_service, document_type_service, presenters, audit_service, group_service, search_service, teams_notification_service
from ..services.booking_service import Actor
from ..services.settings_service import get_app_settings
from ..services.comment_images import ImageReference, ReferencedImage, validated_images, resolve_image, is_image
from .deps import current_admin, current_user, get_booking

router = APIRouter(prefix="/bookings", tags=["bookings"])


def _assert_can_view(
    booking: DeploymentBooking,
    admin: AdminPrincipal | None,
    user: UserPrincipal | None,
) -> None:
    """Any signed-in user may read any change record.

    Tenants need to see the whole board's workload, so viewing, reading,
    cloning and commenting are open to every authenticated account. Changing a
    record is not: that goes through ``booking_service.schedule_actor``. Internal RM notes stay
    hidden from tenants, but that is decided by role in the comment routes, not
    here.
    """
    if admin is None and user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")


def _assert_not_management(
    db: Session,
    admin: AdminPrincipal | None,
    user: UserPrincipal | None,
) -> None:
    principal = admin or user
    if principal is not None and group_service.is_management(db, principal.user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Management access is read-only.")


@router.post("", response_model=BookingCreated, status_code=status.HTTP_201_CREATED)
async def create_booking(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: str = Form(...),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingCreated:
    """Create a booking and its required deployment documents atomically.

    A slot is not considered booked until every document category configured as
    mandatory has been supplied and stored successfully.  This keeps the UI and
    API rules aligned: callers cannot create an incomplete booking by bypassing
    the browser and posting JSON directly.
    """
    enforce(request, "create-booking", limit=20, window_seconds=300)
    _assert_not_management(db, admin, user)
    if admin is not None:
        actor = Actor(is_admin=True, admin_username=admin.username, user_id=admin.user_id)
    elif user is not None:
        actor = Actor(is_admin=False, requester_email=user.email, user_id=user.user_id)
    else:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")

    try:
        booking_payload = BookingCreate.model_validate_json(payload)
    except PydanticValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc

    clone_source = None
    if booking_payload.clone_source_id is not None:
        clone_source = db.get(DeploymentBooking, booking_payload.clone_source_id)
        if clone_source is None:
            raise HTTPException(404, "The source schedule no longer exists.")
        _assert_can_view(clone_source, admin, user)

    form = await request.form()
    app_settings = get_app_settings(db)
    doc_types = document_type_service.active_types(db)
    uploads: list[tuple[object, list[object]]] = []
    missing: list[str] = []

    # Required/Single/Multiple come from the active configured document types.
    for doc_type in doc_types:
        files = [
            item
            for item in form.getlist(f"document_{doc_type.key}")
            if getattr(item, "filename", "")
        ]
        if doc_type.is_required and not files:
            missing.append(doc_type.label)
        if len(files) > 1 and not doc_type.allow_multiple:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"“{doc_type.label}” accepts a single file.",
            )
        if files:
            uploads.append((doc_type, files))

    # Files for a disabled or unknown type are refused rather than silently dropped.
    active_keys = {t.key for t in doc_types}
    for field in form.keys():
        if not field.startswith("document_") or field[len("document_"):] in active_keys:
            continue
        if any(getattr(item, "filename", "") for item in form.getlist(field)):
            document_type_service.uploadable(db, field[len("document_"):])

    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Required deployment document missing: " + ", ".join(missing),
        )

    booking: DeploymentBooking | None = None
    try:
        booking = booking_service.create_booking(db, booking_payload, actor, commit=False)
        for doc_type, files in uploads:
            attachment_service.save_uploads(
                db, booking, doc_type, files, actor, commit=False  # type: ignore[arg-type]
            )
        if clone_source is not None:
            booking_service.audit(db, actor, "BOOKING_CLONED", booking,
                new_values={"source_id": clone_source.id, "source_reference": clone_source.booking_reference})
        db.commit()
        db.refresh(booking)
    except Exception:
        db.rollback()
        if booking is not None and booking.id is not None:
            attachment_service.remove_booking_directory(booking.id)
        raise

    # Delivery runs only after this response is sent. The worker opens its own DB
    # session, so a slow/unavailable Teams endpoint never stalls the single Uvicorn worker.
    background_tasks.add_task(teams_notification_service.notify_booking_created_background, booking.id)
    detail = presenters.booking_detail(db, booking, app_settings, is_admin=actor.is_admin, user_id=actor.user_id)
    return BookingCreated(booking=detail, message=booking_service.success_message(db, booking))


class ScheduleSearchResult(BaseModel):
    id: int
    booking_reference: str
    tenant_name: str
    deployment_date: date
    status: str
    change_number: str | None


@router.get("/search", response_model=list[ScheduleSearchResult])
def search_schedules(
    q: str = Query(min_length=2, max_length=100),
    before_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
):
    if admin is None and user is None:
        raise HTTPException(401, "Authentication required.")
    query = q.strip().upper()
    if len(query) < 2:
        raise HTTPException(422, "Enter at least two characters of the Schedule No.")
    # Every change record is readable by any signed-in user, so search covers
    # them all rather than only the caller's own.
    stmt = select(DeploymentBooking).where(DeploymentBooking.booking_reference.icontains(query, autoescape=True))
    if before_id is not None:
        stmt = stmt.where(DeploymentBooking.id < before_id)
    return [ScheduleSearchResult(id=b.id, booking_reference=b.booking_reference, tenant_name=b.tenant_name,
        deployment_date=b.deployment_date, status=b.status, change_number=b.change_number)
        for b in db.scalars(stmt.order_by(DeploymentBooking.id.desc()).limit(25)).all()]


@router.get("/upcoming", response_model=TenantUpcoming)
def tenant_upcoming_schedules(
    tenant_id: int = Query(ge=1),
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_user),
) -> TenantUpcoming:
    """One tenant's open schedules from today, grouped only into weeks that hold one."""
    return search_service.tenant_upcoming(db, search_service.get_tenant(db, tenant_id))


@router.get("/history", response_model=list[ScheduleListItem])
def schedule_history(
    tenant_id: int | None = Query(default=None, ge=1),
    q: str | None = Query(default=None, max_length=100),
    days: int | None = Query(default=None, ge=1, le=search_service.MAX_DAYS),
    date_from: date | None = None,
    date_to: date | None = None,
    before_date: date | None = None,
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_user),
) -> list[ScheduleListItem]:
    """Paged schedule history, newest first. Filters combine freely."""
    if (before_date is None) != (before_id is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "before_date and before_id must be sent together."
        )
    if tenant_id is not None:
        search_service.get_tenant(db, tenant_id)
    return search_service.schedule_history(
        db,
        tenant_id=tenant_id,
        window=search_service.date_window(days, date_from, date_to),
        reference=(q or "").strip() or None,
        before=(before_date, before_id) if before_date is not None else None,
        limit=limit,
    )


@router.get("/by-reference/{booking_reference}", response_model=BookingDetail)
def read_booking_by_reference(
    booking_reference: str,
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingDetail:
    if admin is None and user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")
    reference = booking_reference.strip().lower()
    booking = db.scalar(
        select(DeploymentBooking).where(func.lower(DeploymentBooking.booking_reference) == reference)
    )
    if booking is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found.")
    _assert_can_view(booking, admin, user)
    return presenters.booking_detail(
        db, booking, get_app_settings(db), is_admin=admin is not None, user_id=user.user_id if user else None
    )


@router.get("/{booking_id}", response_model=BookingDetail)
def read_booking(
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingDetail:
    _assert_can_view(booking, admin, user)
    return presenters.booking_detail(
        db, booking, get_app_settings(db), is_admin=admin is not None, user_id=user.user_id if user else None
    )


@router.put("/{booking_id}", response_model=BookingDetail)
def update_booking(
    request: Request,
    payload: BookingUpdate,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingDetail:
    actor = booking_service.schedule_actor(db, booking, admin=admin, user=user)
    updated = booking_service.update_booking(db, booking, payload, actor)
    return presenters.booking_detail(db, updated, get_app_settings(db), is_admin=actor.is_admin, user_id=actor.user_id)


@router.delete("/{booking_id}", response_model=BookingSummary)
def cancel_booking(
    request: Request,
    payload: BookingCancel,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingSummary:
    actor = booking_service.schedule_actor(db, booking, admin=admin, user=user)
    cancelled = booking_service.cancel_booking(db, booking, actor, payload.override_reason)
    return presenters.booking_summary(db, cancelled, get_app_settings(db))


@router.get("/{booking_id}/reschedule-options", response_model=list[SlotOptionOut])
def reschedule_options(
    limit: int = Query(default=12, ge=1, le=100),
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> list[SlotOptionOut]:
    """Destinations this caller is allowed to move the booking to.

    Only callers who may reschedule the record get options, so nobody sees
    availability for a record they cannot move.
    """
    actor = booking_service.schedule_actor(db, booking, admin=admin, user=user)
    return [
        presenters.slot_option_out(option)
        for option in booking_service.next_available_slots(db, booking, actor, limit=limit)
    ]


@router.post("/{booking_id}/reschedule", response_model=BookingDetail)
def reschedule_booking(
    payload: RescheduleRequest,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingDetail:
    actor = booking_service.schedule_actor(db, booking, admin=admin, user=user)
    moved = booking_service.reschedule_booking(
        db,
        booking,
        payload.deployment_date,
        payload.slot_number,
        actor,
        payload.override_reason,
    )
    return presenters.booking_detail(db, moved, get_app_settings(db), is_admin=actor.is_admin, user_id=actor.user_id)


def _assert_may_manage_collaborators(
    db: Session, booking: DeploymentBooking, admin: AdminPrincipal | None, user: UserPrincipal | None
) -> int:
    """The rule lives in ``booking_service.collaborator_change_restriction``."""
    principal = admin or user
    error = booking_service.collaborator_change_restriction(
        db, booking, user_id=principal.user_id if principal else None, is_admin=admin is not None
    )
    if error is not None:
        raise error
    return principal.user_id  # type: ignore[union-attr]


def _member_pool_users(db: Session):
    return (
        select(User)
        .join(GroupMembership, GroupMembership.user_id == User.id)
        .join(AccessGroup, AccessGroup.id == GroupMembership.group_id)
        .where(
            AccessGroup.group_type == GroupType.MEMBER_POOL.value,
            AccessGroup.is_system.is_(True),
            User.is_active.is_(True),
            User.is_owner.is_(False),
        )
    )


@router.get("/{booking_id}/collaborator-candidates", response_model=list[dict])
def collaborator_candidates(
    q: str | None = Query(default=None, max_length=100),
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> list[dict]:
    """Search the Member Pool for people to add as collaborators.

    Members of the schedule's tenant group already share access, so they are
    not offered; current collaborators are always listed so they can be removed.
    """
    _assert_may_manage_collaborators(db, booking, admin, user)
    existing = set(db.scalars(select(BookingCollaborator.user_id).where(BookingCollaborator.booking_id == booking.id)).all())
    stmt = _member_pool_users(db).where(User.id != booking.created_by_user_id)
    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where((User.full_name.ilike(term)) | (User.username.ilike(term)) | (User.email.ilike(term)))
    candidates = {u.id: u for u in db.scalars(stmt.distinct().order_by(User.full_name, User.username).limit(50)).all()}
    if existing:
        for u in db.scalars(select(User).where(User.id.in_(existing))).all():
            candidates.setdefault(u.id, u)
    return [
        {"id": u.id, "full_name": u.full_name, "username": u.username, "email": u.email, "selected": u.id in existing}
        for u in sorted(candidates.values(), key=lambda u: (u.id not in existing, u.full_name.lower(), u.username))
    ]


@router.put("/{booking_id}/collaborators", response_model=BookingDetail)
def replace_collaborators(
    payload: CollaboratorsUpdate,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingDetail:
    """Set the schedule's collaborators; additions come from the Member Pool.

    A collaborator gets the scheduler's schedule-level permissions (still
    subject to lock, freeze, date and status rules) and never Admin/RM rights.
    Removal takes effect on the collaborator's next request.
    """
    actor_id = _assert_may_manage_collaborators(db, booking, admin, user)
    user_ids = [uid for uid in dict.fromkeys(payload.user_ids) if uid != booking.created_by_user_id]
    existing = set(db.scalars(select(BookingCollaborator.user_id).where(BookingCollaborator.booking_id == booking.id)).all())
    added = [uid for uid in user_ids if uid not in existing]
    removed = [uid for uid in existing if uid not in set(user_ids)]
    if added:
        eligible = {u.id for u in db.scalars(_member_pool_users(db).where(User.id.in_(added))).all()}
        if eligible != set(added):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Collaborators must be active Member Pool users.",
            )
    actor = (
        Actor(is_admin=True, admin_username=admin.username, user_id=admin.user_id)
        if admin is not None
        else Actor(is_admin=False, requester_email=user.email, user_id=user.user_id,  # type: ignore[union-attr]
                   access=booking_service.ACCESS_SCHEDULER)
    )
    names = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_(added + removed))).all()} if (added or removed) else {}
    if removed:
        db.query(BookingCollaborator).filter(
            BookingCollaborator.booking_id == booking.id, BookingCollaborator.user_id.in_(removed)
        ).delete(synchronize_session=False)
    for uid in added:
        db.add(BookingCollaborator(booking_id=booking.id, user_id=uid, added_by_user_id=actor_id))
    for uid in added:
        booking_service.audit(db, actor, "COLLABORATOR_ADDED", booking,
                              new_values={"collaborator": names.get(uid), "collaborator_user_id": uid})
    for uid in removed:
        booking_service.audit(db, actor, "COLLABORATOR_REMOVED", booking,
                              old_values={"collaborator": names.get(uid), "collaborator_user_id": uid})
    db.commit()
    db.refresh(booking)
    return presenters.booking_detail(db, booking, get_app_settings(db), is_admin=admin is not None, user_id=actor_id)


@router.post("/{booking_id}/start-work", response_model=BookingDetail)
def start_work(
    payload: StartWorkRequest,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingDetail:
    _assert_not_management(db, admin, user)
    if admin is not None:
        actor = Actor(is_admin=True, admin_username=admin.username, user_id=admin.user_id)
    elif user is not None:
        actor = Actor(is_admin=False, requester_email=user.email, user_id=user.user_id)
    else:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")
    updated = booking_service.start_work(db, booking, payload.change_number, actor)
    return presenters.booking_detail(db, updated, get_app_settings(db), is_admin=actor.is_admin, user_id=actor.user_id)




# Discussion is append-only and deliberately independent of scheduling freezes.
# Existing booking audit storage preserves comments without a schema migration.


def _assert_may_write_discussion(db: Session, admin: AdminPrincipal | None, user: UserPrincipal | None) -> None:
    _assert_not_management(db, admin, user)


class CommentCreate(BaseModel):
    image_refs: list[ImageReference] = Field(default_factory=list, max_length=10)
    body: str = Field(min_length=1, max_length=5000)
    internal: bool = False

    @field_validator("body")
    @classmethod
    def meaningful_body(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter a comment.")
        return value


class CommentAttachmentOut(BaseModel):
    id: str
    original_filename: str
    size_bytes: int


class CommentOut(BaseModel):
    images: list[ReferencedImage] = Field(default_factory=list)
    attachments: list[CommentAttachmentOut] = Field(default_factory=list)
    id: int
    body: str
    internal: bool
    author_name: str
    author_id: int
    created_at: datetime


def comment_out(event: BookingAudit) -> CommentOut:
    values = json.loads(event.new_values or "{}")
    return CommentOut(images=values.get("images", []), attachments=values.get("attachments", []), id=event.id, body=values["body"],
                      internal=event.event_type == "INTERNAL_NOTE_ADDED",
                      author_name=values["author_name"], author_id=values["author_id"],
                      created_at=event.created_at)


@router.get("/{booking_id}/comments", response_model=list[CommentOut])
def list_comments(
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
):
    _assert_can_view(booking, admin, user)
    kinds = ["COMMENT_ADDED", "INTERNAL_NOTE_ADDED"] if admin else ["COMMENT_ADDED"]
    stmt = select(BookingAudit).where(BookingAudit.booking_id == booking.id, BookingAudit.event_type.in_(kinds))
    if before_id is not None:
        stmt = stmt.where(BookingAudit.id < before_id)
    return [comment_out(e) for e in db.scalars(stmt.order_by(BookingAudit.id.desc()).limit(limit)).all()]


@router.post("/{booking_id}/comments", response_model=CommentOut, status_code=201)
def add_comment(
    payload: CommentCreate,
    request: Request,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
):
    _assert_can_view(booking, admin, user)
    _assert_may_write_discussion(db, admin, user)
    if payload.internal and admin is None:
        raise HTTPException(403, "Internal notes are restricted to the RM team.")
    enforce(request, "booking-comment", limit=30, window_seconds=300)
    principal = admin or user
    account = db.get(User, principal.user_id)
    images = validated_images(db, booking, payload.image_refs, allow_internal=admin is not None and payload.internal)
    event = audit_service.record(
        db, booking=booking,
        event_type="INTERNAL_NOTE_ADDED" if payload.internal else "COMMENT_ADDED",
        actor_type="ADMIN" if admin else "USER",
        admin_username=admin.username if admin else None,
        requester_email=principal.email,
        new_values={"body": payload.body, "author_id": principal.user_id, "author_name": account.full_name, "images": images},
    )
    db.commit()
    db.refresh(event)
    return comment_out(event)


@router.get("/{booking_id}/audit", response_model=list[AuditEventOut])
def booking_audit(
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
):
    _assert_can_view(booking, admin, user)
    # Discussion has its own tab; internal note contents never enter tenant history.
    stmt = select(BookingAudit).where(
        BookingAudit.booking_id == booking.id,
        BookingAudit.event_type.not_in(["COMMENT_ADDED", "INTERNAL_NOTE_ADDED"]),
    )
    if before_id is not None:
        stmt = stmt.where(BookingAudit.id < before_id)
    return [presenters.audit_event_out(e) for e in db.scalars(stmt.order_by(BookingAudit.id.desc()).limit(limit)).all()]


@router.post("/{booking_id}/comments/upload", response_model=CommentOut, status_code=201)
def add_comment_with_files(
    request: Request,
    body: str = Form(min_length=1, max_length=5000),
    internal: bool = Form(default=False),
    files: list[UploadFile] = File(default=[]),
    image_refs: str = Form(default="[]", max_length=5000),
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
):
    from ..services.comment_attachment_service import save_files
    _assert_can_view(booking, admin, user)
    _assert_may_write_discussion(db, admin, user)
    if internal and admin is None:
        raise HTTPException(403, "Internal notes are restricted to the RM team.")
    if not body.strip():
        raise HTTPException(422, "Enter a comment to describe the attachments.")
    if not files or len(files) > 10:
        raise HTTPException(422, "Attach between 1 and 10 files per comment.")
    enforce(request, "booking-comment", limit=30, window_seconds=300)
    principal = admin or user
    account = db.get(User, principal.user_id)
    try:
        refs = CommentCreate(body=body, internal=internal, image_refs=json.loads(image_refs)).image_refs
    except (ValueError, PydanticValidationError):
        raise HTTPException(422, "Invalid image selection.") from None
    images = validated_images(db, booking, refs, allow_internal=admin is not None and internal)
    paths = []
    try:
        event = audit_service.record(db, booking=booking,
            event_type="INTERNAL_NOTE_ADDED" if internal else "COMMENT_ADDED",
            actor_type="ADMIN" if admin else "USER",
            admin_username=admin.username if admin else None, requester_email=principal.email)
        db.flush()
        attachments = save_files(booking.id, event.id, files, paths)
        event.new_values = json.dumps({"body": body.strip(), "author_id": principal.user_id,
            "author_name": account.full_name, "attachments": attachments, "images": images})
        db.commit()
        db.refresh(event)
        return comment_out(event)
    except Exception:
        db.rollback()
        for path in paths:
            path.unlink(missing_ok=True)
        raise
    finally:
        for upload in files:
            upload.file.close()


@router.get("/{booking_id}/comments/{comment_id}/attachments/{attachment_id}")
def download_comment_attachment(
    comment_id: int,
    attachment_id: str,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
):
    from fastapi.responses import FileResponse
    from ..services.comment_attachment_service import attachment_path
    _assert_can_view(booking, admin, user)
    event = db.get(BookingAudit, comment_id)
    if (event is None or event.booking_id != booking.id
            or event.event_type not in {"COMMENT_ADDED", "INTERNAL_NOTE_ADDED"}
            or (event.event_type == "INTERNAL_NOTE_ADDED" and admin is None)):
        raise HTTPException(404, "Comment attachment not found.")
    attachments = json.loads(event.new_values or "{}").get("attachments", [])
    attachment = next((a for a in attachments if a["id"] == attachment_id), None)
    if attachment is None:
        raise HTTPException(404, "Comment attachment not found.")
    path = attachment_path(booking.id, event.id, attachment["id"])
    if not path.is_file():
        raise HTTPException(404, "Comment attachment file is unavailable.")
    return FileResponse(path, media_type="application/octet-stream", filename=attachment["original_filename"],
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


class ImagePickerPage(BaseModel):
    images: list[ReferencedImage]
    next_before_id: int | None = None


@router.get("/{booking_id}/comment-images", response_model=ImagePickerPage)
def list_comment_images(
    internal: bool = False,
    before_id: int | None = Query(default=None, ge=1),
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
):
    _assert_can_view(booking, admin, user)
    if internal and admin is None:
        raise HTTPException(403, "Internal images are restricted to the RM team.")
    images = []
    if before_id is None:
        for attachment in booking.attachments:
            if is_image(attachment.original_filename):
                images.append(ReferencedImage(kind="document", attachment_id=str(attachment.id), original_filename=attachment.original_filename))
    kinds = ["COMMENT_ADDED", "INTERNAL_NOTE_ADDED"] if internal and admin else ["COMMENT_ADDED"]
    stmt = select(BookingAudit).where(BookingAudit.booking_id == booking.id, BookingAudit.event_type.in_(kinds))
    if before_id is not None:
        stmt = stmt.where(BookingAudit.id < before_id)
    events = list(db.scalars(stmt.order_by(BookingAudit.id.desc()).limit(51)).all())
    for event in events[:50]:
        for attachment in json.loads(event.new_values or "{}").get("attachments", []):
            if is_image(attachment["original_filename"]):
                images.append(ReferencedImage(kind="comment", attachment_id=attachment["id"], comment_id=event.id,
                    original_filename=attachment["original_filename"], internal=event.event_type == "INTERNAL_NOTE_ADDED"))
    return ImagePickerPage(images=images, next_before_id=events[49].id if len(events) > 50 else None)


@router.get("/{booking_id}/comment-images/preview")
def preview_comment_image(
    kind: str,
    attachment_id: str,
    comment_id: int | None = None,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
):
    from fastapi.responses import FileResponse
    _assert_can_view(booking, admin, user)
    try:
        ref = ImageReference(kind=kind, attachment_id=attachment_id, comment_id=comment_id)
    except PydanticValidationError:
        raise HTTPException(422, "Invalid image reference.") from None
    image, path = resolve_image(db, booking, ref, allow_internal=admin is not None)
    # Never preview HTML/SVG or trust an upload's declared content type.
    with path.open("rb") as source:
        signature = source.read(8)
    if signature == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif signature.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    else:
        raise HTTPException(415, "This file cannot be previewed as a PNG or JPEG image.")
    return FileResponse(path, media_type=mime, filename=image.original_filename,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})
