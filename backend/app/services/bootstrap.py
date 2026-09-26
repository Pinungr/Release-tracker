"""First-run initialisation: schema, default slot grid, bootstrap administrator."""
from __future__ import annotations

from datetime import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal
from ..models import ApplicationSetting, DeploymentSlotConfiguration, GroupType, User
from ..security import hash_secret
from .migrations import upgrade_database
from . import group_service

#: Normal production deployment windows run overnight by default.
DEFAULT_SLOT_START = time(21, 0)
DEFAULT_SLOT_END = time(5, 0)
DEFAULT_SLOT_COUNT = 4
_SLOT_WINDOW_MARKER = "slot_default_window_21_05_applied"



def ensure_regular_slot_count(db: Session, required_count: int) -> None:
    """Create any missing normal slot rows up to ``required_count``.

    Reducing the configured capacity never deletes rows, because an older slot
    may still be referenced by an existing booking. The schedule resolver simply
    disables rows above the configured limit. Increasing the limit later makes
    those rows visible again, and genuinely missing rows are created here.
    """
    existing_numbers = set(
        db.scalars(select(DeploymentSlotConfiguration.slot_number)).all()
    )
    for number in range(1, required_count + 1):
        if number in existing_numbers:
            continue
        db.add(
            DeploymentSlotConfiguration(
                slot_number=number,
                name=f"Slot {number}",
                start_time=DEFAULT_SLOT_START,
                end_time=DEFAULT_SLOT_END,
                enabled=True,
            )
        )
    db.flush()


def ensure_slot_configurations(db: Session) -> None:
    """Seed the default grid and apply the POC's 21:00-05:00 window once.

    The marker lets an existing development database adopt the new default on
    the first startup of this build without overwriting later admin edits on
    every application restart.
    """
    ensure_regular_slot_count(db, DEFAULT_SLOT_COUNT)

    marker = db.get(ApplicationSetting, _SLOT_WINDOW_MARKER)
    if marker is None:
        for slot in db.scalars(
            select(DeploymentSlotConfiguration).order_by(DeploymentSlotConfiguration.slot_number)
        ).all():
            slot.start_time = DEFAULT_SLOT_START
            slot.end_time = DEFAULT_SLOT_END
        db.add(ApplicationSetting(key=_SLOT_WINDOW_MARKER, value="true"))

    db.commit()


def ensure_bootstrap_admin(db: Session) -> None:
    """Creates the seed administrator in the shared users table.

    The password is hashed immediately and never persisted in clear text. An
    existing administrator is left untouched so a rotated env var cannot
    silently reset a chosen password.
    """
    username = (settings.bootstrap_admin_username or "").strip()
    if not username:
        return
    existing = db.scalars(select(User).where(User.username == username)).first()
    if existing is not None:
        return
    db.add(
        User(
            full_name="Administrator",
            username=username,
            email=f"{username}@localhost",
            password_hash=hash_secret(settings.bootstrap_admin_password),
            role="ADMIN",
            is_owner=True,
        )
    )
    db.commit()


def ensure_single_owner(db: Session) -> None:
    """Guarantee exactly one protected owner account exists.

    The owner is the only account that may manage other administrators, so a
    database must never be left without one. The bootstrap administrator is
    preferred; otherwise the earliest active administrator is adopted. This is
    also what upgrades a database created before the owner tier existed.
    """
    owner = db.scalars(select(User).where(User.is_owner.is_(True))).first()
    if owner is not None:
        # An owner must remain usable, or nobody can administer administrators.
        owner.role = "ADMIN"
        owner.is_active = True
        db.commit()
        return

    username = (settings.bootstrap_admin_username or "").strip()
    candidate = None
    if username:
        candidate = db.scalars(
            select(User).where(User.username == username, User.role == "ADMIN")
        ).first()
    if candidate is None:
        candidate = db.scalars(
            select(User).where(User.role == "ADMIN").order_by(User.id)
        ).first()
    if candidate is None:
        return
    candidate.is_owner = True
    candidate.is_active = True
    db.commit()



def ensure_group_model(db: Session) -> None:
    """Seed system groups and place existing users into a deterministic home."""
    groups = group_service.ensure_system_groups(db)
    group_service.sync_all_tenant_groups(db)
    # Existing databases predate memberships. Owners stay outside Member Pool;
    # existing Release Managers are migrated into the RM group; all other
    # unassigned users start in Member Pool until Admin gives them a group.
    for user in db.scalars(select(User).order_by(User.id)).all():
        if user.is_owner:
            continue
        if group_service.user_groups(db, user.id):
            group_service.reconcile_member_pool(db, user.id)
            continue
        if user.role == "ADMIN":
            group_service.add_membership(
                db, groups[GroupType.RELEASE_MANAGERS.value], user, actor_user_id=None
            )
        else:
            group_service.reconcile_member_pool(db, user.id)
    db.commit()


def initialise() -> None:
    upgrade_database()
    with SessionLocal() as db:
        ensure_slot_configurations(db)
        ensure_bootstrap_admin(db)
        ensure_single_owner(db)
        ensure_group_model(db)
