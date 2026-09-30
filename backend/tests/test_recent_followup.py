"""Recent unlocks append evidence without reopening scheduling; admins may close at any age."""
from datetime import timedelta

import pytest

from conftest import booking_payload, create_booking, post_booking, promote_to_release_manager, sign_up_and_login
from app.models import AutomaticLockOverride, DeploymentBooking, SlotFreeze
from app.utils.dates import today_local
from test_schedule_access_and_unlock import _day, _edit, _group_id, _join, _upload, _user_id


def historical(db, booking, age, *, status="BOOKED"):
    row = db.get(DeploymentBooking, booking["id"])
    row.deployment_date = today_local() - timedelta(days=age)
    row.status = status
    db.commit()
    return row.deployment_date


def unlock(client, day, slot=None):
    return client.post("/api/admin/lock-overrides", json={"override_date": day.isoformat(), "slot_number": slot})


@pytest.mark.parametrize("age", [0, 1, 7])
def test_recent_unlock_appends_evidence_but_never_reopens_scheduling(admin, user, other_user, tenant, next_monday, db, age):
    booking = create_booking(user, tenant, next_monday, 1)
    bid = booking["id"]
    day = historical(db, booking, age)
    original_ids = {a["id"] for a in booking["attachments"]}
    assert _upload(admin, bid, "SUPPORTING_DOCUMENTS", "locked.pdf").status_code == 423
    assert unlock(admin, day, 1).status_code == 201

    for client in (admin, user):
        detail = client.get(f"/api/bookings/{bid}").json()
        assert detail["can_upload_attachments"] and detail["attachments_add_only"]
        assert not any(detail[key] for key in ("can_edit", "can_cancel", "can_reschedule", "can_manage_attachments", "can_assign_rm", "can_start_work"))
        added = _upload(client, bid, "SUPPORTING_DOCUMENTS", "extra-a.pdf", "extra-b.pdf")
        assert added.status_code == 200, added.text
        assert original_ids <= {a["id"] for a in added.json()["attachments"]}
        assert _upload(client, bid, "TEST_RESULTS", "replacement.pdf").status_code == 423
        assert client.delete(f"/api/bookings/{bid}/attachments/{min(original_ids)}").status_code == 423
        assert client.post(f"/api/bookings/{bid}/attachments/bulk-delete", json={"attachment_ids": list(original_ids)}).status_code == 423
        assert _edit(client, booking, impacted_region="EMEA").status_code == 423
        assert client.request("DELETE", f"/api/bookings/{bid}", json={}).status_code == 423
        assert client.post(f"/api/bookings/{bid}/reschedule", json={"deployment_date": next_monday.isoformat(), "slot_number": 2}).status_code == 423
        assert post_booking(client, booking_payload(tenant, day, 2)).status_code == 423
        # Comments remain append-only, including while document uploads are locked.
        comment = client.post(f"/api/bookings/{bid}/comments", json={"body": "Follow-up evidence added."})
        assert comment.status_code == 201, comment.text
    assert admin.post(f"/api/admin/bookings/{bid}/move", json={"deployment_date": next_monday.isoformat(), "slot_number": 2}).status_code == 423
    rm_id = promote_to_release_manager(admin, other_user)
    assert admin.post(f"/api/admin/bookings/{bid}/assign-users", json={"user_ids": [rm_id]}).status_code == 423
    assert other_user.post(f"/api/bookings/{bid}/start-work", json={"change_number": "CHG-123"}).status_code == 423
    assert admin.post(f"/api/admin/bookings/{bid}/status", json={"status": "CANCELLED"}).status_code == 423
    assert admin.post(f"/api/admin/day-capacity/{day.isoformat()}/add-slot").status_code == 423
    restored = admin.delete(f"/api/admin/lock-overrides/{day.isoformat()}?slot_number=1")
    assert restored.status_code == 204
    assert _upload(user, bid, "SUPPORTING_DOCUMENTS", "locked-again.pdf").status_code == 423
    assert not user.get(f"/api/bookings/{bid}").json()["can_upload_attachments"]
    assert len(user.get(f"/api/bookings/{bid}").json()["attachments"]) == len(original_ids) + 4


def test_older_unlock_expires_for_uploads_but_can_be_restored(admin, user, tenant, next_monday, db):
    booking = create_booking(user, tenant, next_monday, 1)
    day = historical(db, booking, 8)
    assert unlock(admin, day).status_code == 423
    db.add(AutomaticLockOverride(override_date=day, slot_number=None))
    db.commit()
    assert _upload(admin, booking["id"], "SUPPORTING_DOCUMENTS", "expired.pdf").status_code == 423
    assert not admin.get(f"/api/bookings/{booking['id']}").json()["can_upload_attachments"]
    assert admin.delete(f"/api/admin/lock-overrides/{day.isoformat()}").status_code == 204
    comment = user.post(f"/api/bookings/{booking['id']}/comments", json={"body": "Older record follow-up."})
    assert comment.status_code == 201, comment.text


def test_recent_slot_unlock_does_not_unlock_other_slots_and_date_unlock_absorbs_it(admin, user, tenant, next_monday, db):
    first = create_booking(user, tenant, next_monday, 1)
    second = create_booking(user, tenant, next_monday, 2)
    day = historical(db, first, 0)
    historical(db, second, 0)
    assert unlock(admin, day, 1).status_code == 201
    assert _upload(user, first["id"], "SUPPORTING_DOCUMENTS", "one.pdf").status_code == 200
    assert _upload(user, second["id"], "SUPPORTING_DOCUMENTS", "two.pdf").status_code == 423
    board = _day(admin, day)
    assert board["automatic_lock"] and not board["date_unlocked"] and not board["emergency_open"]
    assert not any(s["bookable"] for s in board["slots"])
    assert board["regular_slots_total"] == board["regular_slots_used"] == 2
    assert next(s for s in board["slots"] if s["slot_number"] == 1)["lock_override"] == "SLOT"
    assert unlock(admin, day).status_code == 201
    assert _upload(user, second["id"], "SUPPORTING_DOCUMENTS", "two.pdf").status_code == 200
    assert _day(admin, day)["date_unlocked"]
    assert admin.delete(f"/api/admin/lock-overrides/{day.isoformat()}").status_code == 204
    assert _upload(user, first["id"], "SUPPORTING_DOCUMENTS", "three.pdf").status_code == 423
    audit = admin.get("/api/admin/audit").json()
    assert all(e["new_values"]["scope"] == "ADDITIONAL_UPLOADS" for e in audit if e["event_type"] == "AUTOMATIC_LOCK_UNLOCKED")


def test_recent_uploads_keep_tenant_collaborator_and_management_authorization(admin, anon, user, other_user, tenant, next_monday, db):
    colleague = sign_up_and_login(anon, "colleague")
    collaborator = sign_up_and_login(anon, "collaborator")
    manager = sign_up_and_login(anon, "manager")
    try:
        _join(admin, colleague, _group_id(admin, tenant_id=tenant))
        _join(admin, manager, _group_id(admin, group_type="RELEASE_MANAGERS"))
        _join(admin, manager, _group_id(admin, group_type="MANAGEMENT"))
        booking = create_booking(user, tenant, next_monday, 1)
        assert user.put(f"/api/bookings/{booking['id']}/collaborators", json={"user_ids": [_user_id(collaborator)]}).status_code == 200
        day = historical(db, booking, 1)
        assert unlock(other_user, day).status_code == 403
        assert unlock(admin, day).status_code == 201
        for client, allowed in ((colleague, True), (collaborator, True), (other_user, False), (manager, False)):
            detail = client.get(f"/api/bookings/{booking['id']}").json()
            assert detail["can_upload_attachments"] is allowed
            assert _upload(client, booking["id"], "SUPPORTING_DOCUMENTS", "extra.pdf").status_code == (200 if allowed else 403)
        assert manager.post(f"/api/admin/bookings/{booking['id']}/status", json={"status": "COMPLETED"}).status_code == 403
    finally:
        for client in (colleague, collaborator, manager):
            client.close()


@pytest.mark.parametrize("record_status", ["COMPLETED", "CANCELLED"])
def test_closed_and_cancelled_records_keep_upload_restrictions(admin, user, tenant, next_monday, db, record_status):
    booking = create_booking(user, tenant, next_monday, 1)
    day = historical(db, booking, 1, status=record_status)
    assert unlock(admin, day).status_code == 201
    assert _upload(user, booking["id"], "SUPPORTING_DOCUMENTS", "tenant.pdf").status_code == 400
    assert _upload(admin, booking["id"], "SUPPORTING_DOCUMENTS", "admin.pdf").status_code == (200 if record_status == "COMPLETED" else 400)
    assert not admin.get(f"/api/bookings/{booking['id']}").json()["can_close"]
    assert admin.post(f"/api/admin/bookings/{booking['id']}/status", json={"status": "COMPLETED"}).status_code == 400


@pytest.mark.parametrize("age", [0, 7, 8, 90, -14])
@pytest.mark.parametrize("record_status", ["BOOKED", "IN_PROGRESS"])
def test_admin_and_rm_can_close_at_any_age_without_unlock_or_start(admin, user, other_user, tenant, next_monday, db, age, record_status):
    booking = create_booking(user, tenant, next_monday, 1)
    bid = booking["id"]
    promote_to_release_manager(admin, other_user)
    day = historical(db, booking, age, status=record_status)
    db.add(SlotFreeze(freeze_date=day, slot_number=1))
    db.commit()
    assert admin.put("/api/admin/settings", json={"booking_freeze_dates": 25}).status_code == 200
    for client in (admin, other_user):
        detail = client.get(f"/api/bookings/{bid}").json()
        assert detail["can_close"] and not detail["can_edit"]
    assert not user.get(f"/api/bookings/{bid}").json()["can_close"]
    assert user.post(f"/api/admin/bookings/{bid}/status", json={"status": "COMPLETED"}).status_code == 403
    result = other_user.post(f"/api/admin/bookings/{bid}/status", json={"status": "COMPLETED"})
    assert result.status_code == 200, result.text
    detail = result.json()
    assert detail["status"] == "COMPLETED" and not detail["can_close"]
    assert detail["change_number"] is None and detail["work_started_at"] is None
    assert len(detail["attachments"]) == len(booking["attachments"])
    audit = admin.get(f"/api/admin/audit?booking_id={bid}").json()
    event = next(e for e in audit if e["event_type"] == "BOOKING_STATUS_CHANGED")
    assert event["old_values"]["status"] == record_status
    assert event["new_values"]["status"] == "COMPLETED"
    assert any(e["event_type"] == "BOOKING_CREATED" for e in audit)
