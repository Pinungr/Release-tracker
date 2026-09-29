"""Drop the single-column booking tenant index

``ix_booking_tenant_date`` (tenant_id, deployment_date) leads with tenant_id,
so it serves every lookup the single-column index did. Keeping both only adds
write cost to every booking and gives the planner a worse choice for the
tenant-by-date searches.

Revision ID: 20260929_0007
Revises: 20260929_0006
"""
from typing import Sequence, Union

from alembic import op


revision: str = '20260929_0007'
down_revision: Union[str, None] = '20260929_0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_deployment_bookings_tenant_id', table_name='deployment_bookings')


def downgrade() -> None:
    op.create_index('ix_deployment_bookings_tenant_id', 'deployment_bookings', ['tenant_id'], unique=False)
