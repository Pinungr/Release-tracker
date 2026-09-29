"""Tenant-aware audit and indexes for tenant search, history and audit filters

* ``booking_audit.tenant_id`` lets Central Audit filter by tenant without a
  join, and keeps working for schedules that were hard-deleted (their
  ``booking_id`` is nulled on delete, so a join would lose that history).
* ``ix_booking_tenant_date`` serves "this tenant's schedules ordered by date"
  for both upcoming search and history.
* ``ix_booking_audit_tenant_id_id`` / ``ix_booking_audit_created_at`` serve the
  audit tenant filter (paged newest-first by id) and the date filters.

Revision ID: 20260929_0006
Revises: 20260926_0005
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20260929_0006'
down_revision: Union[str, None] = '20260926_0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('booking_audit') as batch:
        batch.add_column(sa.Column('tenant_id', sa.Integer(), nullable=True))
        batch.create_foreign_key(
            'fk_booking_audit_tenant', 'tenants', ['tenant_id'], ['id'], ondelete='SET NULL'
        )

    bind = op.get_bind()
    # Events whose schedule still exists take its tenant.
    bind.execute(sa.text(
        "UPDATE booking_audit SET tenant_id = ("
        "  SELECT b.tenant_id FROM deployment_bookings b WHERE b.id = booking_audit.booking_id"
        ") WHERE booking_id IS NOT NULL"
    ))
    # Events of hard-deleted schedules recover it from the stored snapshot.
    valid = {row[0] for row in bind.execute(sa.text("SELECT id FROM tenants"))}
    orphans = bind.execute(sa.text(
        "SELECT id, old_values, new_values FROM booking_audit "
        "WHERE tenant_id IS NULL AND booking_reference IS NOT NULL"
    )).fetchall()
    for event_id, old_raw, new_raw in orphans:
        tenant_id = None
        for raw in (old_raw, new_raw):
            try:
                value = json.loads(raw or "{}").get("tenant_id")
            except (ValueError, AttributeError):
                continue
            if isinstance(value, int) and value in valid:
                tenant_id = value
                break
        if tenant_id is not None:
            bind.execute(
                sa.text("UPDATE booking_audit SET tenant_id = :t WHERE id = :i"),
                {"t": tenant_id, "i": event_id},
            )

    op.create_index('ix_booking_audit_tenant_id_id', 'booking_audit', ['tenant_id', 'id'])
    op.create_index('ix_booking_audit_created_at', 'booking_audit', ['created_at'])
    op.create_index('ix_booking_tenant_date', 'deployment_bookings', ['tenant_id', 'deployment_date'])


def downgrade() -> None:
    op.drop_index('ix_booking_tenant_date', table_name='deployment_bookings')
    op.drop_index('ix_booking_audit_created_at', table_name='booking_audit')
    op.drop_index('ix_booking_audit_tenant_id_id', table_name='booking_audit')
    with op.batch_alter_table('booking_audit') as batch:
        batch.drop_constraint('fk_booking_audit_tenant', type_='foreignkey')
        batch.drop_column('tenant_id')
