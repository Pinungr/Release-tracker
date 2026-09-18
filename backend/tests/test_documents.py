"""File upload, validation, readiness and download authorisation."""
from __future__ import annotations

import io

from conftest import booking_payload

OWNER = {"requester_email": "rahul.menon@example.com", "booking_pin": "123456"}


def _create(client, day, slot=1):
    return client.post("/api/bookings", json=booking_payload(day, slot)).json()


def _upload(client, booking_id, category, filename, content=b"payload", **extra):
    data = {"category": category, **OWNER}
    data.update(extra)
    return client.post(
        f"/api/bookings/{booking_id}/attachments",
        data=data,
        files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
    )


def test_upload_works_and_updates_readiness(client, next_monday):
    created = _create(client, next_monday)
    booking_id = created["booking"]["id"]
    assert created["booking"]["documents"] == {
        **created["booking"]["documents"],
        "provided_required": 0,
        "total_required": 4,
        "percent": 0,
        "complete": False,
    }

    response = _upload(client, booking_id, "TEST_RESULTS", "results.pdf")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["documents"]["provided_required"] == 1
    assert body["documents"]["percent"] == 25
    assert "Validation Plan" in body["documents"]["missing_labels"]
    assert len(body["attachments"]) == 1
    assert body["attachments"][0]["original_filename"] == "results.pdf"
    # Stored under a generated name, not the uploaded one.
    assert "stored_filename" not in body["attachments"][0]


def test_all_required_documents_makes_readiness_complete(client, next_monday):
    booking_id = _create(client, next_monday)["booking"]["id"]
    for category, name in [
        ("TEST_RESULTS", "results.pdf"),
        ("INVENTORY", "inventory.xlsx"),
        ("IMPLEMENTATION_PLAN", "plan.docx"),
        ("VALIDATION_PLAN", "validation.docx"),
    ]:
        assert _upload(client, booking_id, category, name).status_code == 200
    detail = client.get(f"/api/bookings/{booking_id}").json()
    assert detail["documents"]["complete"] is True
    assert detail["documents"]["percent"] == 100
    assert detail["documents"]["missing_labels"] == []


def test_disallowed_extension_is_rejected(client, next_monday):
    booking_id = _create(client, next_monday)["booking"]["id"]
    response = _upload(client, booking_id, "TEST_RESULTS", "malware.exe")
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_oversized_file_is_rejected(client, admin_headers, next_monday):
    booking_id = _create(client, next_monday)["booking"]["id"]
    client.put("/api/admin/settings", json={"max_file_size_mb": 1}, headers=admin_headers)
    response = _upload(client, booking_id, "TEST_RESULTS", "big.zip", content=b"x" * (1024 * 1024 + 10))
    assert response.status_code == 413


def test_empty_file_is_rejected(client, next_monday):
    booking_id = _create(client, next_monday)["booking"]["id"]
    response = _upload(client, booking_id, "TEST_RESULTS", "empty.txt", content=b"")
    assert response.status_code == 400


def test_traversal_filename_is_sanitised(client, next_monday):
    booking_id = _create(client, next_monday)["booking"]["id"]
    response = _upload(client, booking_id, "TEST_RESULTS", "../../../../etc/passwd.txt")
    assert response.status_code == 200
    name = response.json()["attachments"][0]["original_filename"]
    assert ".." not in name and "/" not in name and "\\" not in name


def test_single_file_category_keeps_only_the_latest_upload(client, next_monday):
    booking_id = _create(client, next_monday)["booking"]["id"]
    _upload(client, booking_id, "IMPLEMENTATION_PLAN", "plan-v1.docx")
    body = _upload(client, booking_id, "IMPLEMENTATION_PLAN", "plan-v2.docx").json()
    plans = [a for a in body["attachments"] if a["category"] == "IMPLEMENTATION_PLAN"]
    assert len(plans) == 1
    assert plans[0]["original_filename"] == "plan-v2.docx"


def test_supporting_documents_accept_multiple_files(client, next_monday):
    booking_id = _create(client, next_monday)["booking"]["id"]
    _upload(client, booking_id, "SUPPORTING_DOCUMENTS", "a.png")
    body = _upload(client, booking_id, "SUPPORTING_DOCUMENTS", "b.png").json()
    extras = [a for a in body["attachments"] if a["category"] == "SUPPORTING_DOCUMENTS"]
    assert len(extras) == 2


def test_upload_requires_ownership(client, next_monday):
    booking_id = _create(client, next_monday)["booking"]["id"]
    anonymous = client.post(
        f"/api/bookings/{booking_id}/attachments",
        data={"category": "TEST_RESULTS"},
        files={"file": ("x.pdf", io.BytesIO(b"data"), "application/pdf")},
    )
    assert anonymous.status_code == 401

    wrong_pin = _upload(client, booking_id, "TEST_RESULTS", "x.pdf", booking_pin="000000")
    assert wrong_pin.status_code == 403


def test_admin_can_upload_without_the_pin(client, admin_headers, next_monday):
    booking_id = _create(client, next_monday)["booking"]["id"]
    response = client.post(
        f"/api/bookings/{booking_id}/attachments",
        data={"category": "DBA_SCRIPT"},
        files={"file": ("script.sql", io.BytesIO(b"select 1;"), "text/plain")},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text


def test_download_requires_a_manage_token_or_admin(client, admin_headers, next_monday):
    booking_id = _create(client, next_monday)["booking"]["id"]
    attachment_id = _upload(client, booking_id, "TEST_RESULTS", "results.pdf").json()["attachments"][0][
        "id"
    ]
    path = f"/api/bookings/{booking_id}/attachments/{attachment_id}/download"

    assert client.get(path).status_code == 403
    assert client.get(f"{path}?token=not-a-real-token").status_code == 403

    token = client.post(f"/api/bookings/{booking_id}/verify-owner", json=OWNER).json()["manage_token"]
    owner = client.get(f"{path}?token={token}")
    assert owner.status_code == 200
    assert owner.headers["content-type"] == "application/octet-stream"
    assert "attachment" in owner.headers["content-disposition"]

    assert client.get(path, headers=admin_headers).status_code == 200


def test_a_manage_token_cannot_read_another_bookings_files(client, next_monday):
    first = _create(client, next_monday, slot=1)
    second = client.post(
        "/api/bookings", json=booking_payload(next_monday, 2, tenant_name="Encounters")
    ).json()
    attachment_id = _upload(client, second["booking"]["id"], "TEST_RESULTS", "other.pdf").json()[
        "attachments"
    ][0]["id"]
    response = client.get(
        f"/api/bookings/{second['booking']['id']}/attachments/{attachment_id}/download"
        f"?token={first['manage_token']}"
    )
    assert response.status_code == 403


def test_attachment_can_be_deleted_by_the_owner(client, next_monday):
    booking_id = _create(client, next_monday)["booking"]["id"]
    attachment_id = _upload(client, booking_id, "TEST_RESULTS", "results.pdf").json()["attachments"][0][
        "id"
    ]
    response = client.request(
        "DELETE", f"/api/bookings/{booking_id}/attachments/{attachment_id}", json=OWNER
    )
    assert response.status_code == 200
    assert response.json()["attachments"] == []


def test_attachment_delete_rejects_a_wrong_pin(client, next_monday):
    booking_id = _create(client, next_monday)["booking"]["id"]
    attachment_id = _upload(client, booking_id, "TEST_RESULTS", "results.pdf").json()["attachments"][0][
        "id"
    ]
    response = client.request(
        "DELETE",
        f"/api/bookings/{booking_id}/attachments/{attachment_id}",
        json={"requester_email": OWNER["requester_email"], "booking_pin": "000000"},
    )
    assert response.status_code == 403


def test_mandatory_document_set_is_configurable(client, admin_headers, next_monday):
    client.put(
        "/api/admin/settings",
        json={"mandatory_documents": ["IMPLEMENTATION_PLAN"]},
        headers=admin_headers,
    )
    booking_id = _create(client, next_monday)["booking"]["id"]
    detail = client.get(f"/api/bookings/{booking_id}").json()
    assert detail["documents"]["total_required"] == 1
    body = _upload(client, booking_id, "IMPLEMENTATION_PLAN", "plan.docx").json()
    assert body["documents"]["complete"] is True
