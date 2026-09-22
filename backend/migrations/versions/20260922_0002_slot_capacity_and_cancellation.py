"""Replace daily slot overrides with per-date capacity; record who cancelled

The Daily Override feature bundled three unrelated knobs onto a date (an
absolute normal-slot count, an emergency on/off switch and a note). Slot
capacity is now a single number per date -- the default from Booking Rules,
adjusted by an administrator adding or removing slots on that one date -- and
emergency changes are governed only by the global setting plus holiday rules.

Revision ID: 20260922_0002
Revises: 20260921_0001
Create Date: 2026-09-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20260922_0002'
down_revision: Union[str, None] = '20260921_0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'daily_slot_capacity',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('capacity_date', sa.Date(), nullable=False),
        sa.Column('slot_count', sa.Integer(), nullable=False),
        sa.Column('updated_by_user_id', sa.Integer(), nullable=True),
        sa.Column(
            'updated_at',
            sa.DateTime(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['updated_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('capacity_date'),
    )

    # Carry over any per-date slot count an administrator had already set.
    # ``emergency_enabled`` and ``note`` are deliberately dropped: emergency
    # availability is no longer a per-date override.
    op.execute(
        sa.text(
            "INSERT INTO daily_slot_capacity (capacity_date, slot_count) "
            "SELECT override_date, regular_slots FROM daily_slot_overrides "
            "WHERE regular_slots IS NOT NULL"
        )
    )
    op.drop_table('daily_slot_overrides')

    with op.batch_alter_table('deployment_bookings') as batch:
        batch.add_column(sa.Column('cancelled_by_user_id', sa.Integer(), nullable=True))
        batch.create_foreign_key(
            'fk_bookings_cancelled_by_user',
            'users',
            ['cancelled_by_user_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    with op.batch_alter_table('deployment_bookings') as batch:
        batch.drop_constraint('fk_bookings_cancelled_by_user', type_='foreignkey')
        batch.drop_column('cancelled_by_user_id')

    op.create_table(
        'daily_slot_overrides',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('override_date', sa.Date(), nullable=False),
        sa.Column('regular_slots', sa.Integer(), nullable=True),
        sa.Column('emergency_enabled', sa.Boolean(), nullable=True),
        sa.Column('note', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('override_date'),
    )
    op.execute(
        sa.text(
            "INSERT INTO daily_slot_overrides (override_date, regular_slots) "
            "SELECT capacity_date, slot_count FROM daily_slot_capacity"
        )
    )
    op.drop_table('daily_slot_capacity')
