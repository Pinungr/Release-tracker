"""Admin/RM lifecycle reopening preserves evidence and scheduling restrictions."""
from datetime import timedelta

import pytest

from conftest import create_booking, promote_to_release_manager, sign_up_and_login
from app.models import BookingAudit, DeploymentBooking, SlotFreeze
from app.utils.dates import now_utc, today_local
from test_schedule_access_and_unlock import _group_id, _join


@pytest.mark.parametrize("actor_name", ["owner", "rm"])
@pytest.mark.parametrize("previous_status", ["BOOKED", "IN_PROGRESS"])
@pytest.mark.parametrize("age", [0, 7, 90, -14])
def test_reopen_at_any_age_preserves_previous_status_and_scheduling_locks(admin, user, other_user, tenant, next_monday, db, actor_name, previous_status, age):
    booking = create_booking(user, tenant, next_monday, 1)
    bid = booking["id"]
    path = f"/api/bookings/{bid}"
    admin_path = f"/api/admin/bookings/{bid}"
    rm_id = promote_to_release_manager(admin, other_user)
    assert admin.post(admin_path + "/assign-users", json={"user_ids": [rm_id]}).status_code == 200
    if previous_status == "IN_PROGRESS":
        assert other_user.post(path + "/start-work", json={"change_number": "CHG-REOPEN"}).status_code == 200
    assert user.post(path + "/comments", json={"body": "Keep this conversation after reopening."}).status_code == 201
    row = db.get(DeploymentBooking, bid)
    row.deployment_date = today_local() - timedelta(days=age)
    db.add(SlotFreeze(freeze_date=row.deployment_date, slot_number=1))
    db.commit()
    assert admin.put("/api/admin/settings", json={"booking_freeze_dates": 25}).status_code == 200
    before = admin.get(path).json()
    comments = user.get(path + "/comments").json()
    closed = admin.post(admin_path + "/status", json={"status": "COMPLETED"})
    assert closed.status_code == 200, closed.text
    for client in (admin, other_user):
        assert client.get(path).json()["can_reopen"]
    assert not user.get(path).json()["can_reopen"]
    assert user.post(admin_path + "/reopen").status_code == 403
    audit_before = admin.get(f"/api/admin/audit?booking_id={bid}").json()
    actor = admin if actor_name == "owner" else other_user
    reopened = actor.post(admin_path + "/reopen")
    assert reopened.status_code == 200, reopened.text
    detail = reopened.json()
    assert detail["status"] == previous_status
    assert detail["can_close"] and not detail["can_reopen"]
    for key in ("id", "booking_reference", "deployment_date", "slot_number", "change_number", "work_started_at", "work_started_by_user_id", "assigned_users", "attachments", "documents"):
        assert detail[key] == before[key], key
    assert user.get(path + "/comments").json() == comments
    assert detail["is_locked"]
    assert not any(detail[key] for key in ("can_edit", "can_reschedule", "can_cancel", "can_manage_attachments", "can_assign_rm", "can_start_work"))
    assert actor.post(path + "/reschedule", json={"deployment_date": next_monday.isoformat(), "slot_number": 2}).status_code == 423
    assert actor.request("DELETE", path, json={}).status_code == 423
    events = admin.get(f"/api/admin/audit?booking_id={bid}").json()
    assert {e["id"] for e in audit_before} < {e["id"] for e in events}
    event = next(e for e in events if e["event_type"] == "BOOKING_REOPENED")
    assert event["old_values"] == {"status": "COMPLETED"}
    assert event["new_values"] == {"status": previous_status}
    assert event["admin_username"] == ("testadmin" if actor_name == "owner" else "user2")
    assert actor.post(admin_path + "/reopen").status_code == 400
    assert admin.get(f"/api/admin/audit?booking_id={bid}").json() == events


def test_each_reopen_restores_the_latest_closure_and_future_workflow(admin, user, other_user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    bid = booking["id"]
    admin_path = f"/api/admin/bookings/{bid}"
    rm_id = promote_to_release_manager(admin, other_user)
    assert admin.post(admin_path + "/assign-users", json={"user_ids": [rm_id]}).status_code == 200
    assert admin.post(admin_path + "/status", json={"status": "COMPLETED"}).status_code == 200
    first = admin.post(admin_path + "/reopen")
    assert first.status_code == 200 and first.json()["status"] == "BOOKED"
    assert first.json()["can_edit"] and first.json()["can_reschedule"]
    assert user.get(f"/api/bookings/{bid}").json()["can_edit"]
    assert other_user.post(f"/api/bookings/{bid}/start-work", json={"change_number": "CHG-LATEST"}).status_code == 200
    assert other_user.post(admin_path + "/status", json={"status": "COMPLETED"}).status_code == 200
    latest = other_user.post(admin_path + "/reopen")
    assert latest.status_code == 200, latest.text
    assert latest.json()["status"] == "IN_PROGRESS"
    assert latest.json()["change_number"] == "CHG-LATEST"
    assert latest.json()["can_start_work"]
    assert len(admin.get("/api/admin/audit", params={"booking_id": bid, "event_type": "BOOKING_REOPENED"}).json()) == 2


@pytest.mark.parametrize("record_status", ["BOOKED", "IN_PROGRESS", "CANCELLED"])
def test_only_closed_records_can_reopen(admin, user, tenant, next_monday, db, record_status):
    booking = create_booking(user, tenant, next_monday, 1)
    bid = booking["id"]
    row = db.get(DeploymentBooking, bid)
    row.status = record_status
    db.commit()
    before = admin.get(f"/api/admin/audit?booking_id={bid}").json()
    result = admin.post(f"/api/admin/bookings/{bid}/reopen")
    assert result.status_code == 400, result.text
    assert admin.get(f"/api/bookings/{bid}").json()["status"] == record_status
    assert not admin.get(f"/api/bookings/{bid}").json()["can_reopen"]
    assert admin.get(f"/api/admin/audit?booking_id={bid}").json() == before


def test_management_cannot_reopen_even_with_rm_membership(admin, anon, user, other_user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    bid = booking["id"]
    promote_to_release_manager(admin, other_user)
    _join(admin, other_user, _group_id(admin, group_type="MANAGEMENT"))
    assert admin.post(f"/api/admin/bookings/{bid}/status", json={"status": "COMPLETED"}).status_code == 200
    assert other_user.post(f"/api/admin/bookings/{bid}/reopen").status_code == 403
    assert not other_user.get(f"/api/bookings/{bid}").json()["can_reopen"]
    assert anon.post(f"/api/admin/bookings/{bid}/reopen").status_code == 401
    outsider = sign_up_and_login(anon, "outsider")
    try:
        assert outsider.post(f"/api/admin/bookings/{bid}/reopen").status_code == 403
    finally:
        outsider.close()


@pytest.mark.parametrize("started", [False, True])
def test_imported_closed_records_without_valid_audit_keep_work_details(admin, user, tenant, next_monday, db, started):
    booking = create_booking(user, tenant, next_monday, 1)
    bid = booking["id"]
    row = db.get(DeploymentBooking, bid)
    row.status = "COMPLETED"
    if started:
        row.change_number = "CHG-LEGACY"
        row.work_started_at = now_utc()
        db.add(BookingAudit(booking_id=bid, event_type="BOOKING_STATUS_CHANGED", actor_type="ADMIN", old_values="invalid legacy JSON", new_values='{"status":"COMPLETED"}'))
    db.commit()
    reopened = admin.post(f"/api/admin/bookings/{bid}/reopen")
    assert reopened.status_code == 200, reopened.text
    detail = reopened.json()
    assert detail["status"] == ("IN_PROGRESS" if started else "BOOKED")
    assert detail["change_number"] == ("CHG-LEGACY" if started else None)
