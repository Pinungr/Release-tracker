"""Deployment document upload, readiness, and authenticated authorization.

Access is decided by created_by_user_id or the ADMIN role — there is no PIN,
no manage token and no unauthenticated path to a stored file.
"""
from __future__ import annotations

import io

from conftest import create_booking

CATEGORIES = [
    ("TEST_RESULTS", "results.pdf"),
    ("INVENTORY", "inventory.xlsx"),
    ("IMPLEMENTATION_PLAN", "plan.docx"),
    ("VALIDATION_PLAN", "validation.docx"),
]


def _upload(client, booking_id, category, filename, content=b"payload"):
    return client.post(
        f"/api/bookings/{booking_id}/attachments",
        data={"category": category},
        files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
    )


def test_owner_can_upload_and_readiness_updates(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    assert booking["documents"]["total_required"] == 4
    assert booking["documents"]["provided_required"] == 0

    response = _upload(user, booking["id"], "TEST_RESULTS", "results.pdf")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["documents"]["provided_required"] == 1
    assert body["documents"]["percent"] == 25
    assert "Validation Plan" in body["documents"]["missing_labels"]
    assert body["attachments"][0]["original_filename"] == "results.pdf"
    # The internally generated name is never exposed.
    assert "stored_filename" not in body["attachments"][0]


def test_all_required_documents_make_the_record_complete(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    for category, name in CATEGORIES:
        assert _upload(user, booking["id"], category, name).status_code == 200

    detail = user.get(f"/api/bookings/{booking['id']}").json()
    assert detail["documents"]["complete"] is True
    assert detail["documents"]["percent"] == 100
    assert detail["documents"]["missing_labels"] == []


def test_all_six_document_categories_are_offered(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    labels = {item["category"] for item in booking["documents"]["items"]}
    assert labels == {
        "TEST_RESULTS",
        "INVENTORY",
        "IMPLEMENTATION_PLAN",
        "VALIDATION_PLAN",
        "DBA_SCRIPT",
        "SUPPORTING_DOCUMENTS",
    }


def test_dba_script_and_supporting_documents_are_optional(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    optional = {
        item["category"] for item in booking["documents"]["items"] if not item["required"]
    }
    assert optional == {"DBA_SCRIPT", "SUPPORTING_DOCUMENTS"}


def test_unsupported_file_type_is_rejected(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    response = _upload(user, booking["id"], "TEST_RESULTS", "malware.exe")
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_oversized_file_is_rejected(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    admin.put("/api/admin/settings", json={"max_file_size_mb": 1})
    response = _upload(
        user, booking["id"], "TEST_RESULTS", "big.zip", content=b"x" * (1024 * 1024 + 10)
    )
    assert response.status_code == 413


def test_empty_file_is_rejected(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    assert _upload(user, booking["id"], "TEST_RESULTS", "empty.txt", content=b"").status_code == 400


def test_filename_is_sanitised_against_traversal(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    response = _upload(user, booking["id"], "TEST_RESULTS", "../../../../etc/passwd.txt")
    assert response.status_code == 200
    name = response.json()["attachments"][0]["original_filename"]
    assert ".." not in name and "/" not in name and "\\" not in name


def test_single_file_category_keeps_only_the_latest(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    _upload(user, booking["id"], "IMPLEMENTATION_PLAN", "plan-v1.docx")
    body = _upload(user, booking["id"], "IMPLEMENTATION_PLAN", "plan-v2.docx").json()
    plans = [a for a in body["attachments"] if a["category"] == "IMPLEMENTATION_PLAN"]
    assert len(plans) == 1
    assert plans[0]["original_filename"] == "plan-v2.docx"


def test_supporting_documents_accept_multiple_files(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    _upload(user, booking["id"], "SUPPORTING_DOCUMENTS", "a.png")
    body = _upload(user, booking["id"], "SUPPORTING_DOCUMENTS", "b.png").json()
    extras = [a for a in body["attachments"] if a["category"] == "SUPPORTING_DOCUMENTS"]
    assert len(extras) == 2


# --------------------------------------------------------------------------- #
# Authorization
# --------------------------------------------------------------------------- #


def test_anonymous_callers_cannot_upload(anon, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    assert _upload(anon, booking["id"], "TEST_RESULTS", "x.pdf").status_code == 401


def test_another_user_cannot_upload_or_delete(user, other_user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    attachment_id = _upload(user, booking["id"], "TEST_RESULTS", "results.pdf").json()["attachments"][0][
        "id"
    ]

    assert _upload(other_user, booking["id"], "TEST_RESULTS", "evil.pdf").status_code == 403
    assert (
        other_user.delete(f"/api/bookings/{booking['id']}/attachments/{attachment_id}").status_code
        == 403
    )


def test_admin_can_upload_to_any_change(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    assert _upload(admin, booking["id"], "DBA_SCRIPT", "script.sql").status_code == 200


def test_download_requires_ownership_or_admin(anon, admin, user, other_user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    attachment_id = _upload(user, booking["id"], "TEST_RESULTS", "results.pdf").json()["attachments"][0][
        "id"
    ]
    path = f"/api/bookings/{booking['id']}/attachments/{attachment_id}/download"

    assert anon.get(path).status_code == 401
    assert other_user.get(path).status_code == 403

    owner = user.get(path)
    assert owner.status_code == 200
    assert owner.headers["content-type"] == "application/octet-stream"
    assert "attachment" in owner.headers["content-disposition"]
    assert owner.headers["x-content-type-options"] == "nosniff"

    assert admin.get(path).status_code == 200


def test_owner_can_delete_their_own_document(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    attachment_id = _upload(user, booking["id"], "TEST_RESULTS", "results.pdf").json()["attachments"][0][
        "id"
    ]
    response = user.delete(f"/api/bookings/{booking['id']}/attachments/{attachment_id}")
    assert response.status_code == 200
    assert response.json()["attachments"] == []


def test_attachment_metadata_is_owner_or_admin_only(anon, admin, user, other_user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    path = f"/api/bookings/{booking['id']}/attachments"
    assert anon.get(path).status_code == 401
    assert other_user.get(path).status_code == 403
    assert user.get(path).status_code == 200
    assert admin.get(path).status_code == 200


def test_mandatory_document_set_is_configurable(admin, user, tenant, next_monday):
    admin.put("/api/admin/settings", json={"mandatory_documents": ["IMPLEMENTATION_PLAN"]})
    booking = create_booking(user, tenant, next_monday, 1)
    assert booking["documents"]["total_required"] == 1
    body = _upload(user, booking["id"], "IMPLEMENTATION_PLAN", "plan.docx").json()
    assert body["documents"]["complete"] is True


def test_completing_a_change_requires_the_mandatory_documents(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    blocked = admin.post(f"/api/admin/bookings/{booking['id']}/status", json={"status": "COMPLETED"})
    assert blocked.status_code == 400
    assert "Required deployment document missing" in blocked.json()["detail"]

    forced = admin.post(
        f"/api/admin/bookings/{booking['id']}/status",
        json={"status": "COMPLETED", "override_reason": "Filed in the change record."},
    )
    assert forced.status_code == 200
    assert forced.json()["status"] == "COMPLETED"
