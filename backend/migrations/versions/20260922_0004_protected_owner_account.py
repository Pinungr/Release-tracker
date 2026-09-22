"""Add the protected owner account flag

Before this revision any administrator could reset another administrator's
password or demote them, so a single promotion handed over the whole
installation. Administrators now manage tenant users only; acting on an ADMIN
account is reserved for one protected owner, and the owner account itself is
never a valid target.

The earliest existing administrator is adopted as the owner so an upgraded
database is never left without one. ``bootstrap.ensure_single_owner`` re-checks
this on every start-up.

Revision ID: 20260922_0004
Revises: 20260922_0003
Create Date: 2026-09-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20260922_0004'
down_revision: Union[str, None] = '20260922_0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.add_column(
            sa.Column(
                'is_owner', sa.Boolean(), server_default=sa.false(), nullable=False
            )
        )
    # Adopt the earliest administrator as the owner of an existing database.
    op.execute(
        sa.text(
            "UPDATE users SET is_owner = true WHERE id = ("
            "  SELECT MIN(id) FROM users WHERE role = 'ADMIN'"
            ")"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.drop_column('is_owner')
