"""Baseline the existing Production Deployment Scheduler schema.

Revision ID: 20260918_0001
Revises:
Create Date: 2026-09-18
"""
from __future__ import annotations

from alembic import op

from app import models  # noqa: F401 - populate Base.metadata
from app.database import Base

revision = "20260918_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This is the baseline revision for installations created before Alembic
    # was introduced. New installations build the model schema here; legacy
    # installations are stamped to this revision by the startup migrator.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
