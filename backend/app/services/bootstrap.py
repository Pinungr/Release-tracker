"""First-run initialisation: schema, default slot grid, bootstrap administrator."""
from __future__ import annotations

from datetime import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal
from ..models import DeploymentSlotConfiguration, User
from ..security import hash_secret
from .migrations import upgrade_database

#: Four normal deployment slots per working day. Emergency changes are a
#: separate admin-only queue and never occupy a slot.
DEFAULT_SLOTS = [
    (1, "Slot 1", time(7, 0), time(9, 0)),
    (2, "Slot 2", time(9, 0), time(11, 0)),
    (3, "Slot 3", time(11, 0), time(13, 0)),
    (4, "Slot 4", time(14, 0), time(16, 0)),
]


def ensure_slot_configurations(db: Session) -> None:
    if db.scalar(select(DeploymentSlotConfiguration.id)) is not None:
        return
    for number, name, start, end in DEFAULT_SLOTS:
        db.add(
            DeploymentSlotConfiguration(
                slot_number=number,
                name=name,
                start_time=start,
                end_time=end,
                enabled=True,
            )
        )
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
