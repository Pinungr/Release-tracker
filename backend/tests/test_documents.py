"""Deployment document upload, readiness, and authenticated authorization.

Access is decided by created_by_user_id or the ADMIN role — there is no PIN,
no manage token and no unauthenticated path to a stored file.
"""
from __future__ import annotations


import io

from conftest import booking_payload, create_booking, post_booking

CATEGORIES = [
    ("TEST_RESULTS", "results.pdf"),
    ("INVENTORY", "inventory.xlsx"),
    ("IMPLEMENTATION_PLAN", "plan.docx"),
    ("VALIDATION_PLAN", "validation.docx"),
    ("DBA_SCRIPT", "dba.sql"),
]


def _upload(client, booking_id, category, filename, content=b"payload"):
    return client.post(
        f"/api/bookings/{booking_id}/attachments",
        data={"category": category},
        files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
    )




def test_booking_rejects_missing_required_document(user, tenant, next_monday):
    response = post_booking(
        user,
        booking_payload(tenant, next_monday, 1),
        omit_documents={"DBA_SCRIPT"},
    )
    assert response.status_code == 422
    assert "DBA Script" in response.json()["detail"]
    # A rejected document set must not reserve the slot.
    retry = post_booking(user, booking_payload(tenant, next_monday, 1))
    assert retry.status_code == 201


def test_optional_contact_and_summary_fields_can_be_blank(user, tenant, next_monday):
    response = post_booking(
        user,
        booking_payload(
            tenant,
            next_monday,
            1,
            verifier_email=None,
            implementation_summary=None,
        ),
    )
    assert response.status_code == 201, response.text
    booking = response.json()["booking"]
    assert booking["requester_email"]
    assert booking["verifier_email"] == ""
    assert booking["implementation_summary"] == ""


def test_json_only_booking_cannot_bypass_required_documents(user, tenant, next_monday):
    response = user.post(
        "/api/bookings", json=booking_payload(tenant, next_monday, 1)
    )
    assert response.status_code == 422

def test_booking_is_created_with_all_required_documents(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    assert booking["documents"]["total_required"] == 5
    assert booking["documents"]["provided_required"] == 5
    assert booking["documents"]["percent"] == 100
    assert booking["documents"]["complete"] is True
    assert len(booking["attachments"]) == 5


def test_replacing_a_required_document_keeps_record_complete(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    response = _upload(user, booking["id"], "TEST_RESULTS", "results-v2.pdf")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["documents"]["provided_required"] == 5
    assert body["documents"]["percent"] == 100
    results = [a for a in body["attachments"] if a["category"] == "TEST_RESULTS"]
    assert len(results) == 1
    assert results[0]["original_filename"] == "results-v2.pdf"


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


def test_only_supporting_documents_are_optional_by_default(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    optional = {
        item["category"] for item in booking["documents"]["items"] if not item["required"]
    }
    assert optional == {"SUPPORTING_DOCUMENTS"}


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


def test_any_user_can_download_but_only_the_owner_can_change_documents(
    anon, admin, user, other_user, tenant, next_monday
):
    booking = create_booking(user, tenant, next_monday, 1)
    attachment_id = _upload(user, booking["id"], "TEST_RESULTS", "results.pdf").json()["attachments"][0][
        "id"
    ]
    path = f"/api/bookings/{booking['id']}/attachments/{attachment_id}/download"

    assert anon.get(path).status_code == 401
    # Reading a schedule includes its documents...
    assert other_user.get(path).status_code == 200
    # ...but only the owner (or an administrator) may add or remove them.
    assert _upload(other_user, booking["id"], "SUPPORTING_DOCUMENTS", "mine.pdf").status_code == 403
    assert other_user.delete(
        f"/api/bookings/{booking['id']}/attachments/{attachment_id}"
    ).status_code == 403
    assert attachment_id in [a["id"] for a in user.get(f"/api/bookings/{booking['id']}").json()["attachments"]]

    owner = user.get(path)
    assert owner.status_code == 200
    assert owner.headers["content-type"] == "application/octet-stream"
    assert "attachment" in owner.headers["content-disposition"]
    assert owner.headers["x-content-type-options"] == "nosniff"

    assert admin.get(path).status_code == 200


def test_owner_can_delete_their_own_document(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    uploaded = _upload(user, booking["id"], "TEST_RESULTS", "results.pdf").json()
    attachment_id = next(
        a["id"] for a in uploaded["attachments"] if a["category"] == "TEST_RESULTS"
    )
    response = user.delete(f"/api/bookings/{booking['id']}/attachments/{attachment_id}")
    assert response.status_code == 200
    assert all(a["category"] != "TEST_RESULTS" for a in response.json()["attachments"])


def test_locked_owner_cannot_delete_documents_but_admin_can(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    uploaded = _upload(user, booking["id"], "TEST_RESULTS", "results.pdf").json()
    attachment_id = next(
        a["id"] for a in uploaded["attachments"] if a["category"] == "TEST_RESULTS"
    )
    frozen = admin.post(
        "/api/admin/slot-freezes",
        json={"freeze_date": next_monday.isoformat(), "slot_number": 1},
    )
    assert frozen.status_code == 200

    blocked = user.delete(f"/api/bookings/{booking['id']}/attachments/{attachment_id}")
    assert blocked.status_code == 423

    allowed = admin.delete(f"/api/bookings/{booking['id']}/attachments/{attachment_id}")
    assert allowed.status_code == 200
    assert all(a["category"] != "TEST_RESULTS" for a in allowed.json()["attachments"])




def test_mandatory_document_set_is_configurable(admin, user, tenant, next_monday):
    admin.put("/api/admin/settings", json={"mandatory_documents": ["IMPLEMENTATION_PLAN"]})
    booking = create_booking(user, tenant, next_monday, 1)
    assert booking["documents"]["total_required"] == 1
    assert booking["documents"]["complete"] is True


def test_completing_a_change_requires_the_mandatory_documents(admin, user, other_user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    implementation = next(
        a for a in booking["attachments"] if a["category"] == "IMPLEMENTATION_PLAN"
    )
    removed = user.delete(f"/api/bookings/{booking['id']}/attachments/{implementation['id']}")
    assert removed.status_code == 200

    from conftest import promote_to_release_manager
    rm_id = promote_to_release_manager(admin, other_user)
    assert admin.post(f"/api/admin/bookings/{booking['id']}/assign-users", json={"user_ids": [rm_id]}).status_code == 200
    assert other_user.post(f"/api/bookings/{booking['id']}/start-work", json={"change_number": "CHG-123"}).status_code == 200

    blocked = admin.post(f"/api/admin/bookings/{booking['id']}/status", json={"status": "COMPLETED"})
    assert blocked.status_code == 400
    assert "Required deployment document missing" in blocked.json()["detail"]

    forced = admin.post(
        f"/api/admin/bookings/{booking['id']}/status",
        json={"status": "COMPLETED", "override_reason": "Filed in the change record."},
    )
    assert forced.status_code == 200
    assert forced.json()["status"] == "COMPLETED"
