"""Database-driven document types: required/optional, single/multiple, multi-file upload and deletion."""
from __future__ import annotations

import io

from conftest import booking_payload, create_booking, post_booking


def _types(admin) -> dict[str, dict]:
    return {t["key"]: t for t in admin.get("/api/admin/document-types").json()}


def _set(admin, key: str, **changes):
    response = admin.put(f"/api/admin/document-types/{_types(admin)[key]['id']}", json=changes)
    assert response.status_code == 200, response.text
    return response


def _upload(client, booking_id, category, *names):
    return client.post(
        f"/api/bookings/{booking_id}/attachments",
        data={"category": category},
        files=[("file", (name, io.BytesIO(b"-- sql"), "application/octet-stream")) for name in names],
    )


def _files(response, category):
    return [a for a in response.json()["attachments"] if a["category"] == category]


def _audit_types(admin) -> list[str]:
    return [e["event_type"] for e in admin.get("/api/admin/audit?limit=500").json()]


def test_existing_document_types_are_seeded_in_order(admin):
    types = admin.get("/api/admin/document-types").json()
    assert [t["label"] for t in types] == [
        "Non-Production Test Result",
        "Inventory File",
        "Implementation Document",
        "Validation Plan",
        "DBA Script",
        "Supporting Documents",
    ]
    assert [t["key"] for t in types if not t["is_required"]] == ["SUPPORTING_DOCUMENTS"]
    assert [t["key"] for t in types if t["allow_multiple"]] == ["SUPPORTING_DOCUMENTS"]


def test_multiple_file_type_accepts_several_files_stored_separately(admin, user, tenant, next_monday):
    _set(admin, "DBA_SCRIPT", allow_multiple=True)
    booking = create_booking(user, tenant, next_monday, 1)
    response = _upload(user, booking["id"], "DBA_SCRIPT", "deployment.sql", "rollback.sql", "validation.sql")
    assert response.status_code == 200, response.text
    scripts = _files(response, "DBA_SCRIPT")
    # The booking was created with dba.sql; each upload is its own record.
    assert sorted(a["original_filename"] for a in scripts) == ["dba.sql", "deployment.sql", "rollback.sql", "validation.sql"]
    assert len({a["id"] for a in scripts}) == 4
    assert all(a["uploaded_by"] == "pinaki@example.com" for a in scripts[1:])
    for attachment in scripts:
        download = user.get(f"/api/bookings/{booking['id']}/attachments/{attachment['id']}/download")
        assert download.status_code == 200

    rollback = next(a for a in scripts if a["original_filename"] == "rollback.sql")
    after = user.delete(f"/api/bookings/{booking['id']}/attachments/{rollback['id']}")
    assert after.status_code == 200
    assert sorted(a["original_filename"] for a in _files(after, "DBA_SCRIPT")) == ["dba.sql", "deployment.sql", "validation.sql"]
    # More files can be added later.
    later = _upload(user, booking["id"], "DBA_SCRIPT", "hotfix.sql")
    assert len(_files(later, "DBA_SCRIPT")) == 4


def test_single_file_type_rejects_several_files_and_replaces_one(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    rejected = _upload(user, booking["id"], "IMPLEMENTATION_PLAN", "a.docx", "b.docx")
    assert rejected.status_code == 422
    assert "single file" in rejected.json()["detail"]
    replaced = _upload(user, booking["id"], "IMPLEMENTATION_PLAN", "plan-v2.docx")
    assert [a["original_filename"] for a in _files(replaced, "IMPLEMENTATION_PLAN")] == ["plan-v2.docx"]
    assert "DOCUMENT_REPLACED" in _audit_types(admin)


def test_booking_creation_enforces_single_file_types(user, tenant, next_monday):
    import json

    payload = booking_payload(tenant, next_monday, 1)
    files = [
        ("document_TEST_RESULTS", ("r.pdf", b"x", "application/pdf")),
        ("document_INVENTORY", ("i.xlsx", b"x", "application/octet-stream")),
        ("document_IMPLEMENTATION_PLAN", ("p1.docx", b"x", "application/octet-stream")),
        ("document_IMPLEMENTATION_PLAN", ("p2.docx", b"x", "application/octet-stream")),
        ("document_VALIDATION_PLAN", ("v.docx", b"x", "application/octet-stream")),
        ("document_DBA_SCRIPT", ("d.sql", b"x", "application/octet-stream")),
    ]
    response = user.post("/api/bookings", data={"payload": json.dumps(payload)}, files=files)
    assert response.status_code == 422
    assert "single file" in response.json()["detail"]


def test_selected_files_are_deleted_and_the_rest_untouched(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    uploaded = _upload(user, booking["id"], "SUPPORTING_DOCUMENTS", "file1.pdf", "file2.pdf", "file3.pdf")
    by_name = {a["original_filename"]: a["id"] for a in _files(uploaded, "SUPPORTING_DOCUMENTS")}

    response = user.post(
        f"/api/bookings/{booking['id']}/attachments/bulk-delete",
        json={"attachment_ids": [by_name["file1.pdf"], by_name["file3.pdf"]]},
    )
    assert response.status_code == 200, response.text
    assert [a["original_filename"] for a in _files(response, "SUPPORTING_DOCUMENTS")] == ["file2.pdf"]
    assert len(response.json()["attachments"]) == 6  # five required documents + file2
    event = next(e for e in admin.get("/api/admin/audit").json() if e["event_type"] == "DOCUMENTS_DELETED")
    assert event["old_values"]["count"] == 2

    missing = user.post(f"/api/bookings/{booking['id']}/attachments/bulk-delete", json={"attachment_ids": [999999]})
    assert missing.status_code == 404


def test_final_required_file_is_protected(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    _set(admin, "SUPPORTING_DOCUMENTS", is_required=True)
    uploaded = _upload(user, booking["id"], "SUPPORTING_DOCUMENTS", "file1.pdf", "file2.pdf")
    file1, file2 = (a["id"] for a in _files(uploaded, "SUPPORTING_DOCUMENTS"))

    assert user.delete(f"/api/bookings/{booking['id']}/attachments/{file1}").status_code == 200
    blocked = user.delete(f"/api/bookings/{booking['id']}/attachments/{file2}")
    assert blocked.status_code == 409
    assert "at least one file must remain" in blocked.json()["detail"]

    again = _upload(user, booking["id"], "SUPPORTING_DOCUMENTS", "file3.pdf", "file4.pdf")
    ids = [a["id"] for a in _files(again, "SUPPORTING_DOCUMENTS")]
    # Deleting every file of a required type in one selection is refused as a whole.
    all_at_once = user.post(f"/api/bookings/{booking['id']}/attachments/bulk-delete", json={"attachment_ids": ids})
    assert all_at_once.status_code == 409
    assert len(_files(user.get(f"/api/bookings/{booking['id']}"), "SUPPORTING_DOCUMENTS")) == 3


def test_required_validation_follows_configuration(admin, user, tenant, next_monday):
    _set(admin, "DBA_SCRIPT", is_required=False)
    optional = post_booking(user, booking_payload(tenant, next_monday, 1), omit_documents={"DBA_SCRIPT"})
    assert optional.status_code == 201, optional.text

    _set(admin, "DBA_SCRIPT", is_required=True)
    required = post_booking(user, booking_payload(tenant, next_monday, 2), omit_documents={"DBA_SCRIPT"})
    assert required.status_code == 422
    assert "DBA Script" in required.json()["detail"]

    changes = [e for e in admin.get("/api/admin/audit").json() if e["event_type"] == "DOCUMENT_TYPE_REQUIREMENT_CHANGED"]
    assert [(e["old_values"]["requirement"], e["new_values"]["requirement"]) for e in changes] == [
        ("Optional", "Required"),
        ("Required", "Optional"),
    ]


def test_new_document_type_is_offered_and_enforced(admin, user, tenant, next_monday):
    created = admin.post(
        "/api/admin/document-types",
        json={"label": "Rollback Plan", "is_required": True, "allow_multiple": True},
    )
    assert created.status_code == 201, created.text
    rollback = next(t for t in created.json() if t["label"] == "Rollback Plan")
    assert rollback["key"] == "ROLLBACK_PLAN"

    catalog = user.get(f"/api/schedule?week={next_monday.isoformat()}").json()["settings"]["document_catalog"]
    assert catalog[-1] == {"category": "ROLLBACK_PLAN", "label": "Rollback Plan", "description": None, "required": True, "multiple": True}

    assert post_booking(user, booking_payload(tenant, next_monday, 1)).status_code == 422
    import json

    from conftest import REQUIRED_BOOKING_DOCUMENTS

    files = [(f"document_{k}", (n, c, "application/octet-stream")) for k, (n, c) in REQUIRED_BOOKING_DOCUMENTS.items()]
    files += [("document_ROLLBACK_PLAN", ("r1.sql", b"x", "text/plain")), ("document_ROLLBACK_PLAN", ("r2.sql", b"x", "text/plain"))]
    response = user.post("/api/bookings", data={"payload": json.dumps(booking_payload(tenant, next_monday, 1))}, files=files)
    assert response.status_code == 201, response.text
    assert len([a for a in response.json()["booking"]["attachments"] if a["category"] == "ROLLBACK_PLAN"]) == 2


def test_disabled_type_keeps_history_but_stops_uploads(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    inventory = next(a for a in booking["attachments"] if a["category"] == "INVENTORY")
    _set(admin, "INVENTORY", is_active=False)

    detail = user.get(f"/api/bookings/{booking['id']}").json()
    kept = next(a for a in detail["attachments"] if a["id"] == inventory["id"])
    assert kept["category_label"] == "Inventory File"
    assert "INVENTORY" not in {i["category"] for i in detail["documents"]["items"]}
    assert user.get(f"/api/bookings/{booking['id']}/attachments/{inventory['id']}/download").status_code == 200
    assert _upload(user, booking["id"], "INVENTORY", "inv2.xlsx").status_code == 409
    # New bookings no longer need it.
    assert post_booking(user, booking_payload(tenant, next_monday, 2), omit_documents={"INVENTORY"}).status_code == 201

    # A type with uploaded files cannot be hard deleted.
    assert admin.delete(f"/api/admin/document-types/{_types(admin)['INVENTORY']['id']}").status_code == 409
    events = _audit_types(admin)
    assert "DOCUMENT_TYPE_DISABLED" in events
    _set(admin, "INVENTORY", is_active=True)
    assert "DOCUMENT_TYPE_ENABLED" in _audit_types(admin)


def test_rename_reorder_mode_and_delete_are_audited(admin):
    types = admin.get("/api/admin/document-types").json()
    _set(admin, "VALIDATION_PLAN", label="Validation Document")
    _set(admin, "DBA_SCRIPT", allow_multiple=True)
    _set(admin, "DBA_SCRIPT", allow_multiple=False)
    duplicate = admin.put(f"/api/admin/document-types/{types[0]['id']}", json={"label": "validation document"})
    assert duplicate.status_code == 409

    reversed_ids = [t["id"] for t in reversed(types)]
    reordered = admin.put("/api/admin/document-types/order", json={"ids": reversed_ids})
    assert reordered.status_code == 200
    assert [t["id"] for t in reordered.json()] == reversed_ids
    assert admin.put("/api/admin/document-types/order", json={"ids": reversed_ids[:-1]}).status_code == 422

    created = admin.post("/api/admin/document-types", json={"label": "Temporary"}).json()
    temporary = next(t for t in created if t["label"] == "Temporary")
    assert admin.delete(f"/api/admin/document-types/{temporary['id']}").status_code == 200

    events = admin.get("/api/admin/audit?limit=500").json()
    kinds = [e["event_type"] for e in events]
    for expected in (
        "DOCUMENT_TYPE_RENAMED", "DOCUMENT_TYPES_REORDERED", "DOCUMENT_TYPE_CREATED", "DOCUMENT_TYPE_DELETED",
    ):
        assert expected in kinds
    modes = [(e["old_values"]["file_mode"], e["new_values"]["file_mode"]) for e in events if e["event_type"] == "DOCUMENT_TYPE_FILE_MODE_CHANGED"]
    assert modes == [("Multiple", "Single"), ("Single", "Multiple")]
    renamed = next(e for e in events if e["event_type"] == "DOCUMENT_TYPE_RENAMED")
    assert (renamed["old_values"]["label"], renamed["new_values"]["label"]) == ("Validation Plan", "Validation Document")
    assert renamed["admin_username"] == "testadmin"


def test_non_admins_cannot_configure_document_types(user, admin):
    type_id = admin.get("/api/admin/document-types").json()[0]["id"]
    assert user.get("/api/admin/document-types").status_code == 403
    assert user.post("/api/admin/document-types", json={"label": "X"}).status_code == 403
    assert user.put(f"/api/admin/document-types/{type_id}", json={"is_required": False}).status_code == 403
    assert user.put("/api/admin/document-types/order", json={"ids": [type_id]}).status_code == 403
    assert user.delete(f"/api/admin/document-types/{type_id}").status_code == 403


def test_switching_multiple_to_single_keeps_existing_files_and_applies_to_new_uploads(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    _upload(user, booking["id"], "SUPPORTING_DOCUMENTS", "s1.pdf", "s2.pdf", "s3.pdf")
    _set(admin, "SUPPORTING_DOCUMENTS", allow_multiple=False)

    # Nothing is deleted or hidden by the switch; Admin/RM can see how many schedules are affected.
    detail = user.get(f"/api/bookings/{booking['id']}").json()
    kept = [a for a in detail["attachments"] if a["category"] == "SUPPORTING_DOCUMENTS"]
    assert len(kept) == 3
    assert _types(admin)["SUPPORTING_DOCUMENTS"]["multi_file_schedules"] == 1
    for attachment in kept:
        assert user.get(f"/api/bookings/{booking['id']}/attachments/{attachment['id']}/download").status_code == 200

    # New uploads follow the Single File rule.
    assert _upload(user, booking["id"], "SUPPORTING_DOCUMENTS", "t1.pdf", "t2.pdf").status_code == 422
    replaced = _upload(user, booking["id"], "SUPPORTING_DOCUMENTS", "final.pdf")
    assert [a["original_filename"] for a in _files(replaced, "SUPPORTING_DOCUMENTS")] == ["final.pdf"]
    assert _types(admin)["SUPPORTING_DOCUMENTS"]["multi_file_schedules"] == 0


def test_booking_creation_rejects_files_for_disabled_or_unknown_types(admin, user, tenant, next_monday):
    import json

    from conftest import REQUIRED_BOOKING_DOCUMENTS

    _set(admin, "SUPPORTING_DOCUMENTS", is_active=False)
    files = [(f"document_{k}", (n, c, "application/octet-stream")) for k, (n, c) in REQUIRED_BOOKING_DOCUMENTS.items()]
    payload = json.dumps(booking_payload(tenant, next_monday, 1))
    extra = ("x.pdf", b"x", "application/pdf")
    disabled = user.post("/api/bookings", data={"payload": payload}, files=files + [("document_SUPPORTING_DOCUMENTS", extra)])
    assert disabled.status_code == 409
    assert "disabled" in disabled.json()["detail"]
    unknown = user.post("/api/bookings", data={"payload": payload}, files=files + [("document_NOT_A_TYPE", extra)])
    assert unknown.status_code == 422
    assert user.post("/api/bookings", data={"payload": payload}, files=files).status_code == 201


def test_attachment_audit_carries_attachment_ids(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    uploaded = _upload(user, booking["id"], "SUPPORTING_DOCUMENTS", "same.pdf", "same.pdf")
    ids = sorted(a["id"] for a in _files(uploaded, "SUPPORTING_DOCUMENTS"))
    events = admin.get(f"/api/admin/audit?booking_id={booking['id']}").json()
    added = sorted(
        e["new_values"]["attachment_id"] for e in events
        if e["event_type"] == "DOCUMENT_ADDED" and e["new_values"]["filename"] == "same.pdf"
    )
    assert added == ids

    user.post(f"/api/bookings/{booking['id']}/attachments/bulk-delete", json={"attachment_ids": ids})
    events = admin.get(f"/api/admin/audit?booking_id={booking['id']}").json()
    bulk = next(e for e in events if e["event_type"] == "DOCUMENTS_DELETED")
    assert sorted(bulk["old_values"]["attachment_ids"]) == ids

    replaced = _upload(user, booking["id"], "IMPLEMENTATION_PLAN", "plan-v2.docx")
    new_id = _files(replaced, "IMPLEMENTATION_PLAN")[0]["id"]
    events = admin.get(f"/api/admin/audit?booking_id={booking['id']}").json()
    event = next(e for e in events if e["event_type"] == "DOCUMENT_REPLACED")
    assert event["new_values"]["attachment_id"] == new_id
    assert len(event["old_values"]["attachment_ids"]) == 1


def test_public_settings_have_no_separate_mandatory_list(user, next_monday):
    settings = user.get(f"/api/schedule?week={next_monday.isoformat()}").json()["settings"]
    assert "mandatory_documents" not in settings
    assert {e["category"] for e in settings["document_catalog"] if e["required"]} == {
        "TEST_RESULTS", "INVENTORY", "IMPLEMENTATION_PLAN", "VALIDATION_PLAN", "DBA_SCRIPT",
    }
