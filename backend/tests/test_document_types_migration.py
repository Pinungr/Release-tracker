"""The 0008 migration carries the old mandatory-documents setting into document types."""
from __future__ import annotations

import json

from alembic import command
from sqlalchemy import text

from app.database import engine
from app.services.migrations import _config


def test_upgrade_seeds_types_from_the_previous_mandatory_setting():
    cfg = _config()
    command.downgrade(cfg, "20260929_0007")
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM application_settings WHERE key = 'mandatory_documents'"))
        connection.execute(
            text("INSERT INTO application_settings (key, value) VALUES ('mandatory_documents', :v)"),
            {"v": json.dumps(["INVENTORY", "DBA_SCRIPT"])},
        )
    command.upgrade(cfg, "head")

    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT key, is_required, allow_multiple, is_active FROM document_types ORDER BY display_order")
        ).all()
        setting = connection.execute(
            text("SELECT value FROM application_settings WHERE key = 'mandatory_documents'")
        ).scalar()
    assert [r[0] for r in rows] == [
        "TEST_RESULTS", "INVENTORY", "IMPLEMENTATION_PLAN", "VALIDATION_PLAN", "DBA_SCRIPT", "SUPPORTING_DOCUMENTS",
    ]
    assert {r[0] for r in rows if r[1]} == {"INVENTORY", "DBA_SCRIPT"}
    assert {r[0] for r in rows if r[2]} == {"SUPPORTING_DOCUMENTS"}
    assert all(r[3] for r in rows)
    # The superseded setting is gone, so there is one source of truth.
    assert setting is None
