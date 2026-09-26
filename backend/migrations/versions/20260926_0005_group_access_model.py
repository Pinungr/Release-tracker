"""Group-based access model

Revision ID: 20260926_0005
Revises: 20260922_0004
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '20260926_0005'
down_revision: Union[str, None] = '20260922_0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'access_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('group_type', sa.String(length=32), nullable=False),
        sa.Column('parent_group_id', sa.Integer(), nullable=True),
        sa.Column('tenant_id', sa.Integer(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('permissions_json', sa.Text(), server_default='{}', nullable=False),
        sa.Column('is_system', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['parent_group_id'], ['access_groups.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id'),
        sa.UniqueConstraint('name', 'parent_group_id', name='uq_access_group_name_parent'),
    )
    op.create_index(op.f('ix_access_groups_group_type'), 'access_groups', ['group_type'], unique=False)
    op.create_index(op.f('ix_access_groups_parent_group_id'), 'access_groups', ['parent_group_id'], unique=False)
    op.create_index(op.f('ix_access_groups_tenant_id'), 'access_groups', ['tenant_id'], unique=True)

    op.create_table(
        'group_memberships',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('added_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['added_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['group_id'], ['access_groups.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('group_id', 'user_id', name='uq_group_membership'),
    )
    op.create_index(op.f('ix_group_memberships_group_id'), 'group_memberships', ['group_id'], unique=False)
    op.create_index(op.f('ix_group_memberships_user_id'), 'group_memberships', ['user_id'], unique=False)

    op.create_table(
        'booking_collaborators',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('booking_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('added_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['added_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['booking_id'], ['deployment_bookings.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('booking_id', 'user_id', name='uq_booking_collaborator'),
    )
    op.create_index(op.f('ix_booking_collaborators_booking_id'), 'booking_collaborators', ['booking_id'], unique=False)
    op.create_index(op.f('ix_booking_collaborators_user_id'), 'booking_collaborators', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_booking_collaborators_user_id'), table_name='booking_collaborators')
    op.drop_index(op.f('ix_booking_collaborators_booking_id'), table_name='booking_collaborators')
    op.drop_table('booking_collaborators')
    op.drop_index(op.f('ix_group_memberships_user_id'), table_name='group_memberships')
    op.drop_index(op.f('ix_group_memberships_group_id'), table_name='group_memberships')
    op.drop_table('group_memberships')
    op.drop_index(op.f('ix_access_groups_tenant_id'), table_name='access_groups')
    op.drop_index(op.f('ix_access_groups_parent_group_id'), table_name='access_groups')
    op.drop_index(op.f('ix_access_groups_group_type'), table_name='access_groups')
    op.drop_table('access_groups')
