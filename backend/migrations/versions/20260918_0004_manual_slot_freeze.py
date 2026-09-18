"""Add administrator-controlled manual slot freezes.

Revision ID: 20260918_0004
Revises: 20260918_0003
Create Date: 2026-09-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260918_0004"
down_revision = "20260918_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The dynamic baseline may already have created this table on a brand-new DB.
    if "slot_freezes" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "slot_freezes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("freeze_date", sa.Date(), nullable=False),
        sa.Column("slot_number", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("freeze_date", "slot_number", name="uq_slot_freeze_date_number"),
    )
    op.create_index("ix_slot_freeze_date", "slot_freezes", ["freeze_date"])


def downgrade() -> None:
    if "slot_freezes" in inspect(op.get_bind()).get_table_names():
        op.drop_table("slot_freezes")
