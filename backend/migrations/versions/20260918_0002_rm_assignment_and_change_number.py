"""Add RM assignment and separate Change No.

Revision ID: 20260918_0002
Revises: 20260918_0001
Create Date: 2026-09-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260918_0002"
down_revision = "20260918_0001"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "deployment_bookings" in tables:
        columns = _columns("deployment_bookings")
        with op.batch_alter_table("deployment_bookings") as batch:
            if "change_number" not in columns:
                batch.add_column(sa.Column("change_number", sa.String(length=64), nullable=True))
            if "work_started_by_user_id" not in columns:
                batch.add_column(sa.Column("work_started_by_user_id", sa.Integer(), nullable=True))
            if "work_started_at" not in columns:
                batch.add_column(sa.Column("work_started_at", sa.DateTime(), nullable=True))

    # Baseline create_all() may already have created this table on a new DB.
    tables = set(inspect(op.get_bind()).get_table_names())
    if "booking_assignments" not in tables:
        op.create_table(
            "booking_assignments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("booking_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("assigned_by_user_id", sa.Integer(), nullable=True),
            sa.Column("assigned_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["booking_id"], ["deployment_bookings.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("booking_id", "user_id", name="uq_booking_assignment_user"),
        )
        op.create_index("ix_booking_assignments_booking_id", "booking_assignments", ["booking_id"])
        op.create_index("ix_booking_assignments_user_id", "booking_assignments", ["user_id"])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "booking_assignments" in inspector.get_table_names():
        op.drop_table("booking_assignments")
    if "deployment_bookings" in inspector.get_table_names():
        columns = _columns("deployment_bookings")
        with op.batch_alter_table("deployment_bookings") as batch:
            for name in ("work_started_at", "work_started_by_user_id", "change_number"):
                if name in columns:
                    batch.drop_column(name)
