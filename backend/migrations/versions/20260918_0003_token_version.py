"""Persist JWT session version on users.

Revision ID: 20260918_0003
Revises: 20260918_0002
Create Date: 2026-09-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260918_0003"
down_revision = "20260918_0002"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "users" not in inspect(op.get_bind()).get_table_names():
        return
    columns = _columns("users")
    if "token_version" not in columns:
        with op.batch_alter_table("users") as batch:
            batch.add_column(
                sa.Column(
                    "token_version",
                    sa.Integer(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )


def downgrade() -> None:
    if "users" not in inspect(op.get_bind()).get_table_names():
        return
    columns = _columns("users")
    if "token_version" in columns:
        with op.batch_alter_table("users") as batch:
            batch.drop_column("token_version")
