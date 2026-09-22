"""First-run initialisation: schema, default slot grid, bootstrap administrator."""
from __future__ import annotations

from datetime import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal
from ..models import ApplicationSetting, DeploymentSlotConfiguration, User
from ..security import hash_secret
from .migrations import upgrade_database

#: Normal production deployment windows run overnight by default.
DEFAULT_SLOT_START = time(21, 0)
DEFAULT_SLOT_END = time(5, 0)
DEFAULT_SLOT_COUNT = 4
_SLOT_WINDOW_MARKER = "slot_default_window_21_05_applied"

DEFAULT_SLOTS = [
    (number, f"Slot {number}", DEFAULT_SLOT_START, DEFAULT_SLOT_END)
    for number in range(1, DEFAULT_SLOT_COUNT + 1)
]


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
        )
    )
    db.commit()


def initialise() -> None:
    upgrade_database()
    with SessionLocal() as db:
        ensure_slot_configurations(db)
        ensure_bootstrap_admin(db)
