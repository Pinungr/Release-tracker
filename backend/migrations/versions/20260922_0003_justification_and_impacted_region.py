"""Add mandatory justification and impacted region to change records

Both are required on every booking, normal and emergency alike. They are added
with an empty-string default so rows created before this revision stay valid;
the API rejects a blank value on every create and edit from here on.

``justification`` is distinct from the existing emergency-only
``business_justification`` and does not replace it.

Revision ID: 20260922_0003
Revises: 20260922_0002
Create Date: 2026-09-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20260922_0003'
down_revision: Union[str, None] = '20260922_0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('deployment_bookings') as batch:
        batch.add_column(
            sa.Column('justification', sa.Text(), server_default='', nullable=False)
        )
        batch.add_column(
            sa.Column(
                'impacted_region', sa.String(length=160), server_default='', nullable=False
            )
        )


def downgrade() -> None:
    with op.batch_alter_table('deployment_bookings') as batch:
        batch.drop_column('impacted_region')
        batch.drop_column('justification')
