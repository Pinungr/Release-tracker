"""Configurable document types, automatic-lock overrides and audit access basis

* ``document_types`` replaces the hard-coded document categories. The six
  existing categories are seeded with their current keys, so every stored
  ``booking_attachments.category`` keeps resolving. Required/optional is taken
  from the ``mandatory_documents`` application setting it supersedes, which is
  then removed.
* ``automatic_lock_overrides`` records an Admin/RM exception to the automatic
  upcoming-date lock for one date (slot_number NULL) or one slot.
* ``booking_audit.actor_access`` records why a non-admin was allowed to act
  (scheduler, tenant member or collaborator).

Revision ID: 20260930_0008
Revises: 20260929_0007
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20260930_0008'
down_revision: Union[str, None] = '20260929_0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: The categories that were hard-coded before this revision, in display order.
LEGACY_TYPES = [
    ("TEST_RESULTS", "Non-Production Test Result", False),
    ("INVENTORY", "Inventory File", False),
    ("IMPLEMENTATION_PLAN", "Implementation Document", False),
    ("VALIDATION_PLAN", "Validation Plan", False),
    ("DBA_SCRIPT", "DBA Script", False),
    ("SUPPORTING_DOCUMENTS", "Supporting Documents", True),
]
LEGACY_MANDATORY = ["TEST_RESULTS", "INVENTORY", "IMPLEMENTATION_PLAN", "VALIDATION_PLAN", "DBA_SCRIPT"]


def upgrade() -> None:
    op.create_table(
        'document_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=40), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('is_required', sa.Boolean(), nullable=False),
        sa.Column('allow_multiple', sa.Boolean(), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('updated_by_user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['updated_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )

    bind = op.get_bind()
    mandatory = LEGACY_MANDATORY
    raw = bind.execute(
        sa.text("SELECT value FROM application_settings WHERE key = 'mandatory_documents'")
    ).scalar()
    if raw is not None:
        try:
            stored = json.loads(raw)
            if isinstance(stored, list):
                mandatory = [str(v) for v in stored]
        except ValueError:
            pass

    table = sa.table(
        'document_types',
        sa.column('key', sa.String), sa.column('label', sa.String),
        sa.column('is_active', sa.Boolean), sa.column('is_required', sa.Boolean),
        sa.column('allow_multiple', sa.Boolean), sa.column('display_order', sa.Integer),
    )
    op.bulk_insert(table, [
        {
            'key': key, 'label': label, 'is_active': True,
            'is_required': key in mandatory, 'allow_multiple': multiple,
            'display_order': index,
        }
        for index, (key, label, multiple) in enumerate(LEGACY_TYPES, start=1)
    ])
    bind.execute(sa.text("DELETE FROM application_settings WHERE key = 'mandatory_documents'"))

    op.create_table(
        'automatic_lock_overrides',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('override_date', sa.Date(), nullable=False),
        sa.Column('slot_number', sa.Integer(), nullable=True),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('override_date', 'slot_number', name='uq_lock_override_date_slot'),
    )
    op.create_index('ix_lock_override_date', 'automatic_lock_overrides', ['override_date'])

    with op.batch_alter_table('booking_audit') as batch:
        batch.add_column(sa.Column('actor_access', sa.String(length=24), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('booking_audit') as batch:
        batch.drop_column('actor_access')
    op.drop_index('ix_lock_override_date', table_name='automatic_lock_overrides')
    op.drop_table('automatic_lock_overrides')

    bind = op.get_bind()
    required = [row[0] for row in bind.execute(sa.text(
        "SELECT key FROM document_types WHERE is_required = :t AND is_active = :t"
    ), {"t": True})]
    bind.execute(
        sa.text("INSERT INTO application_settings (key, value) VALUES ('mandatory_documents', :v)"),
        {"v": json.dumps(required)},
    )
    op.drop_table('document_types')
