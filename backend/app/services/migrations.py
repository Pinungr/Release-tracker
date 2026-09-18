"""Database migration runner.

Older releases used ``Base.metadata.create_all()`` at every startup. From this
release onward Alembic owns schema evolution. An already-existing legacy
scheduler database is stamped at the baseline revision once; a new database is
upgraded normally. Future schema changes must be added as Alembic revisions.
"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from ..database import engine

BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"

# Tables that unmistakably identify the pre-Alembic scheduler database.
LEGACY_TABLES = {"users", "deployment_bookings", "slot_configurations"}


def _config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def upgrade_database() -> None:
    cfg = _config()
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())

    if "alembic_version" not in existing and LEGACY_TABLES.issubset(existing):
        # The current application already created this schema in earlier
        # releases. Mark it as the baseline instead of trying to CREATE the
        # same tables again.
        # Mark the legacy schema at the original baseline, then run every
        # newer migration. Stamping directly to head would silently skip new
        # columns/tables on existing installations.
        command.stamp(cfg, "20260918_0001")

    command.upgrade(cfg, "head")
