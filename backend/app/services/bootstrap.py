"""First-run initialisation: schema, default slot grid, seed administrator."""
from __future__ import annotations

from datetime import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import Base, SessionLocal, engine
from ..models import AdminUser, DeploymentSlotConfiguration
from ..security import hash_secret

DEFAULT_SLOTS = [
    (1, "Slot 1", time(7, 0), time(9, 0), False),
    (2, "Slot 2", time(9, 0), time(11, 0), False),
    (3, "Slot 3", time(11, 0), time(13, 0), False),
    (4, "Slot 4", time(14, 0), time(16, 0), False),
    (5, "Emergency Slot 5", time(16, 0), time(18, 0), True),
]


def create_schema() -> None:
    Base.metadata.create_all(bind=engine)


def ensure_slot_configurations(db: Session) -> None:
    if db.scalar(select(DeploymentSlotConfiguration.id)) is not None:
        return
    for number, name, start, end, emergency in DEFAULT_SLOTS:
        db.add(
            DeploymentSlotConfiguration(
                slot_number=number,
                name=name,
                start_time=start,
                end_time=end,
                is_emergency=emergency,
                enabled=True,
            )
        )
    db.commit()


def ensure_admin_user(db: Session) -> None:
    """Creates the seed administrator from ADMIN_USERNAME / ADMIN_PASSWORD.

    The password is hashed immediately and never persisted in clear text. An
    existing administrator is left untouched so a rotated env var cannot
    silently reset a chosen password.
    """
    username = (settings.admin_username or "").strip()
    if not username:
        return
    existing = db.scalars(select(AdminUser).where(AdminUser.username == username)).first()
    if existing is not None:
        return
    db.add(
        AdminUser(
            username=username,
            password_hash=hash_secret(settings.admin_password),
            display_name="Administrator",
        )
    )
    db.commit()


def initialise() -> None:
    create_schema()
    with SessionLocal() as db:
        ensure_slot_configurations(db)
        ensure_admin_user(db)
