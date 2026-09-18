"""First-run initialisation: schema, default slot grid, seed administrator."""
from __future__ import annotations

from datetime import time

from sqlalchemy import inspect, select, text
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


def migrate_user_tenant_model() -> None:
    """Backfill the independent tenant/creator model for existing databases."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "tenants" not in tables or "users" not in tables or "deployment_bookings" not in tables:
        return

    columns = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in ("tenants", "users", "deployment_bookings")
    }
    additions = {
        "tenants": {
            "tenant_code": "VARCHAR(64)",
            "description": "TEXT",
            "updated_at": "TIMESTAMP",
        },
        "users": {
            "must_change_password": "BOOLEAN DEFAULT FALSE",
            "updated_at": "TIMESTAMP",
        },
        "deployment_bookings": {
            "tenant_id": "INTEGER",
            "created_by_user_id": "INTEGER",
        },
    }
    with engine.begin() as connection:
        for table, table_additions in additions.items():
            for column, definition in table_additions.items():
                if column not in columns[table]:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))

        connection.execute(
            text("UPDATE tenants SET tenant_code = 'TENANT-' || id WHERE tenant_code IS NULL")
        )
        connection.execute(
            text("UPDATE tenants SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
        )
        connection.execute(
            text("UPDATE users SET must_change_password = FALSE WHERE must_change_password IS NULL")
        )
        connection.execute(text("UPDATE users SET role = 'TENANT_USER' WHERE role = 'TENANT'"))
        connection.execute(
            text("UPDATE users SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
        )
        connection.execute(
            text(
                "UPDATE deployment_bookings "
                "SET tenant_id = (SELECT id FROM tenants WHERE lower(trim(name)) = lower(trim(deployment_bookings.tenant_name))) "
                "WHERE tenant_id IS NULL"
            )
        )
        connection.execute(
            text(
                "UPDATE deployment_bookings "
                "SET created_by_user_id = (SELECT id FROM users WHERE lower(email) = lower(deployment_bookings.requester_email)) "
                "WHERE created_by_user_id IS NULL"
            )
        )


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
    migrate_user_tenant_model()
    create_schema()
    with SessionLocal() as db:
        ensure_slot_configurations(db)
        ensure_admin_user(db)
