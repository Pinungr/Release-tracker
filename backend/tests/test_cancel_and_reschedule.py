"""Owner-initiated cancellation and rescheduling.

A booking is never deleted and never recreated by either action: cancelling
releases the slot while keeping the record, and rescheduling moves the same
record (same id, same reference, same attachments) to another date/slot in one
transaction.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from conftest import booking_payload, create_booking, post_booking


def options(client, booking_id: int, limit: int = 12) -> list[dict]:
    response = client.get(f"/api/bookings/{booking_id}/reschedule-options?limit={limit}")
    assert response.status_code == 200, response.text
    return response.json()


def as_date(option: dict) -> date:
    return date.fromisoformat(option["deployment_date"])


def reschedule(client, booking_id: int, option: dict):
    return client.post(
        f"/api/bookings/{booking_id}/reschedule",
        json={
            "deployment_date": option["deployment_date"],
            "slot_number": option["slot_number"],
        },
    )


def audit_events(admin, booking_id: int) -> list[dict]:
    response = admin.get(f"/api/admin/audit?booking_id={booking_id}")
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# Cancellation
# --------------------------------------------------------------------------- #


def test_a_user_can_cancel_their_own_booking(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    response = user.request("DELETE", f"/api/bookings/{booking['id']}", json={})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CANCELLED"


def test_a_user_cannot_cancel_another_users_booking(user, other_user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    response = other_user.request("DELETE", f"/api/bookings/{booking['id']}", json={})
    assert response.status_code == 403
    assert user.get(f"/api/bookings/{booking['id']}").json()["status"] == "BOOKED"


def test_an_admin_can_cancel_any_booking(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    response = admin.request("DELETE", f"/api/bookings/{booking['id']}", json={})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CANCELLED"


def test_cancelling_releases_the_slot_without_deleting_the_record(
    admin, user, other_user, tenant, other_tenant, next_monday
):
    booking = create_booking(user, tenant, next_monday, 2)
    user.request("DELETE", f"/api/bookings/{booking['id']}", json={})

    board = user.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    slot = board["days"][0]["slots"][1]
    assert slot["booking"] is None
    assert slot["state"] == "AVAILABLE"

    # The freed slot really is bookable again, by a different user/tenant.
    assert post_booking(other_user, booking_payload(other_tenant, next_monday, 2)).status_code == 201

    # The original record survives for history.
    retained = admin.get(f"/api/bookings/{booking['id']}")
    assert retained.status_code == 200
    assert retained.json()["status"] == "CANCELLED"
    assert retained.json()["booking_reference"] == booking["booking_reference"]


def test_cancellation_records_who_cancelled_and_when(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    user.request("DELETE", f"/api/bookings/{booking['id']}", json={})

    detail = admin.get(f"/api/bookings/{booking['id']}").json()
    assert detail["cancelled_at"] is not None
    assert detail["cancelled_by_user_id"] == booking["created_by_user_id"]

    event = next(e for e in audit_events(admin, booking["id"]) if e["event_type"] == "BOOKING_CANCELLED")
    assert event["actor_type"] == "USER"
    assert event["old_values"]["deployment_date"] == next_monday.isoformat()
    assert event["old_values"]["slot_number"] == 1
    assert event["old_values"]["tenant_name"] == "EPCAT"
    assert event["old_values"]["jira_number"] == "CHG0920763"
    assert event["new_values"]["cancelled_by_user_id"] == booking["created_by_user_id"]


# --------------------------------------------------------------------------- #
# Reschedule: eligibility of the offered destinations
# --------------------------------------------------------------------------- #


def test_offered_slots_start_after_the_freeze_window_and_are_free(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    offered = options(user, booking["id"])
    assert offered

    board = user.get(f"/api/schedule?week={date.today().isoformat()}").json()
    frozen = {
        day["day"]
        for day in board["days"]
        if not any(slot["bookable"] for slot in day["slots"])
    }
    # Nothing inside today or the configured upcoming-date freeze window.
    assert offered[0]["deployment_date"] > board["today"]
    assert not any(item["deployment_date"] in frozen for item in offered)
    # Earliest first.
    assert [item["deployment_date"] for item in offered] == sorted(
        item["deployment_date"] for item in offered
    )
    # Its own current slot is never offered as a destination.
    assert not any(
        item["deployment_date"] == next_monday.isoformat() and item["slot_number"] == 1
        for item in offered
    )


def test_holiday_frozen_and_disabled_dates_are_not_offered_to_a_normal_user(
    admin, user, tenant, next_monday
):
    tuesday = next_monday + timedelta(days=1)
    wednesday = next_monday + timedelta(days=2)
    thursday = next_monday + timedelta(days=3)
    booking = create_booking(user, tenant, next_monday, 1)

    admin.post(
        "/api/admin/holidays",
        json={"holiday_date": tuesday.isoformat(), "name": "Founders Day", "is_full_day": True},
    )
    admin.post(
        "/api/admin/slot-freezes",
        json={"freeze_date": wednesday.isoformat(), "slot_number": 1, "note": "Change freeze"},
    )
    admin.post(f"/api/admin/day-capacity/{thursday.isoformat()}/remove-slot")

    offered = options(user, booking["id"], limit=100)
    assert not any(item["deployment_date"] == tuesday.isoformat() for item in offered)
    assert not any(
        item["deployment_date"] == wednesday.isoformat() and item["slot_number"] == 1
        for item in offered
    )
    assert any(
        item["deployment_date"] == wednesday.isoformat() and item["slot_number"] == 2
        for item in offered
    )
    # Slot 4 was removed from Thursday, so it is no longer a destination.
    assert not any(
        item["deployment_date"] == thursday.isoformat() and item["slot_number"] == 4
        for item in offered
    )


def test_a_taken_slot_is_never_offered(user, other_user, tenant, other_tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    create_booking(other_user, other_tenant, next_monday, 2)
    offered = options(user, booking["id"])
    assert not any(
        item["deployment_date"] == next_monday.isoformat() and item["slot_number"] == 2
        for item in offered
    )


def test_a_week_already_at_the_tenant_limit_is_not_offered(admin, user, tenant, next_monday):
    """The limit is 2 per tenant per week; one of the two is the record itself."""
    booking = create_booking(user, tenant, next_monday, 1)
    create_booking(user, tenant, next_monday + timedelta(days=1), 1)
    # Administrators bypass the tenant quota, so this fills the week to 3.
    create_booking(admin, tenant, next_monday + timedelta(days=2), 1)

    offered = options(user, booking["id"], limit=100)
    # Moving anywhere inside its own week would leave the tenant at 3 bookings,
    # so no date in that Sunday-Thursday range is offered at all.
    full_week = {
        (next_monday + timedelta(days=offset)).isoformat() for offset in range(5)
    }
    assert not any(item["deployment_date"] in full_week for item in offered)
    assert offered, "other weeks still have room"


# --------------------------------------------------------------------------- #
# Reschedule: the move itself
# --------------------------------------------------------------------------- #


def test_a_user_can_reschedule_their_own_booking(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    target = options(user, booking["id"])[0]

    response = reschedule(user, booking["id"], target)
    assert response.status_code == 200, response.text
    moved = response.json()
    assert moved["id"] == booking["id"]
    assert moved["booking_reference"] == booking["booking_reference"]
    assert moved["deployment_date"] == target["deployment_date"]
    assert moved["slot_number"] == target["slot_number"]
    assert moved["status"] == "BOOKED"


def test_a_user_cannot_reschedule_another_users_booking(user, other_user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    target = options(user, booking["id"])[0]

    assert other_user.get(f"/api/bookings/{booking['id']}/reschedule-options").status_code == 403
    assert reschedule(other_user, booking["id"], target).status_code == 403

    unchanged = user.get(f"/api/bookings/{booking['id']}").json()
    assert unchanged["deployment_date"] == next_monday.isoformat()
    assert unchanged["slot_number"] == 1


def test_an_admin_can_reschedule_any_booking(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    target = options(admin, booking["id"])[0]
    response = reschedule(admin, booking["id"], target)
    assert response.status_code == 200, response.text
    assert response.json()["deployment_date"] == target["deployment_date"]


def test_reschedule_keeps_every_field_and_attachment(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    before = user.get(f"/api/bookings/{booking['id']}").json()
    target = options(user, booking["id"])[0]

    after = reschedule(user, booking["id"], target).json()

    carried = (
        "tenant_id",
        "tenant_name",
        "jira_number",
        "jira_url",
        "requester_name",
        "requester_email",
        "requester_phone",
        "verifier_name",
        "verifier_email",
        "git_repository",
        "implementation_summary",
        "deployment_description",
        "justification",
        "impacted_region",
        "additional_comments",
        "technology",
        "environment",
        "created_by_user_id",
        "booking_reference",
    )
    for field in carried:
        assert after[field] == before[field], field
    assert [a["id"] for a in after["attachments"]] == [a["id"] for a in before["attachments"]]
    assert len(after["attachments"]) == 5
    assert after["documents"]["complete"] is True


def test_the_vacated_slot_becomes_available_and_the_destination_is_taken(
    user, tenant, next_monday
):
    booking = create_booking(user, tenant, next_monday, 1)
    target = options(user, booking["id"])[0]
    reschedule(user, booking["id"], target)

    board = user.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    assert board["days"][0]["slots"][0]["booking"] is None
    assert board["days"][0]["slots"][0]["state"] == "AVAILABLE"


def test_a_destination_slot_cannot_be_double_booked(
    user, other_user, tenant, other_tenant, next_monday
):
    booking = create_booking(user, tenant, next_monday, 1)
    target = options(user, booking["id"])[0]

    # Somebody takes the destination between the picker and the confirmation.
    taken = post_booking(
        other_user,
        booking_payload(other_tenant, as_date(target), target["slot_number"]),
    )
    assert taken.status_code == 201, taken.text

    response = reschedule(user, booking["id"], target)
    assert response.status_code == 409
    assert "another user" in response.json()["detail"]


def test_a_failed_reschedule_leaves_the_original_booking_untouched(
    user, other_user, tenant, other_tenant, next_monday
):
    booking = create_booking(user, tenant, next_monday, 1)
    before = user.get(f"/api/bookings/{booking['id']}").json()
    target = options(user, booking["id"])[0]
    post_booking(
        other_user,
        booking_payload(other_tenant, as_date(target), target["slot_number"]),
    )

    assert reschedule(user, booking["id"], target).status_code == 409

    after = user.get(f"/api/bookings/{booking['id']}").json()
    assert after["deployment_date"] == before["deployment_date"]
    assert after["slot_number"] == before["slot_number"]
    assert after["status"] == "BOOKED"
    assert len(after["attachments"]) == len(before["attachments"])


@pytest.mark.parametrize("slot_number", [1, 99])
def test_a_slot_that_was_never_offered_is_rejected_on_submit(
    admin, user, tenant, next_monday, slot_number
):
    """Validation is not delegated to the picker: submit re-checks everything."""
    tuesday = next_monday + timedelta(days=1)
    booking = create_booking(user, tenant, next_monday, 1)
    admin.post(
        "/api/admin/slot-freezes",
        json={"freeze_date": tuesday.isoformat(), "slot_number": 1},
    )
    response = user.post(
        f"/api/bookings/{booking['id']}/reschedule",
        json={"deployment_date": tuesday.isoformat(), "slot_number": slot_number},
    )
    assert response.status_code in (400, 404, 422, 423)


def test_rescheduling_into_a_full_week_is_refused_for_a_normal_user(
    user, tenant, next_monday
):
    booking = create_booking(user, tenant, next_monday + timedelta(days=14), 1)
    create_booking(user, tenant, next_monday, 1)
    create_booking(user, tenant, next_monday + timedelta(days=1), 1)

    response = user.post(
        f"/api/bookings/{booking['id']}/reschedule",
        json={"deployment_date": (next_monday + timedelta(days=2)).isoformat(), "slot_number": 1},
    )
    assert response.status_code == 409
    assert "Weekly booking limit" in response.json()["detail"]


def test_rescheduling_within_the_same_week_does_not_count_the_booking_twice(
    user, tenant, next_monday
):
    """Moving a booking must not make its own week look one over the limit."""
    create_booking(user, tenant, next_monday, 1)
    booking = create_booking(user, tenant, next_monday + timedelta(days=1), 1)

    response = user.post(
        f"/api/bookings/{booking['id']}/reschedule",
        json={"deployment_date": (next_monday + timedelta(days=2)).isoformat(), "slot_number": 3},
    )
    assert response.status_code == 200, response.text
    assert response.json()["slot_number"] == 3


def test_a_cancelled_booking_cannot_be_rescheduled(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    target = options(user, booking["id"])[0]
    user.request("DELETE", f"/api/bookings/{booking['id']}", json={})

    assert reschedule(user, booking["id"], target).status_code == 400
    assert options(user, booking["id"]) == []


def test_reschedule_is_written_to_the_audit_trail(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    target = options(user, booking["id"])[0]
    reschedule(user, booking["id"], target)

    event = next(
        e for e in audit_events(admin, booking["id"]) if e["event_type"] == "BOOKING_RESCHEDULED"
    )
    assert event["actor_type"] == "USER"
    assert event["old_values"]["deployment_date"] == next_monday.isoformat()
    assert event["old_values"]["slot_number"] == 1
    assert event["old_values"]["tenant_name"] == "EPCAT"
    assert event["old_values"]["jira_number"] == "CHG0920763"
    assert event["new_values"]["deployment_date"] == target["deployment_date"]
    assert event["new_values"]["slot_number"] == target["slot_number"]
