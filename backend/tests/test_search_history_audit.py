"""Tenant search, schedule history and Central Audit filters.

Rows are mostly inserted directly so the tests do not depend on which weekday
they run: past dates and dates inside the freeze window cannot be booked
through the API, yet real databases are full of them.
"""
from __future__ import annotations

import itertools
from datetime import date, datetime, timedelta

import pytest

from app.models import BookingAudit, DeploymentBooking
from app.utils.dates import today_local, week_start
from conftest import create_booking, create_tenant

_refs = itertools.count(1)


def insert(db, tenant_id: int, tenant_name: str, day: date, slot: int | None = 1,
           status: str = "BOOKED", emergency: bool = False) -> DeploymentBooking:
    row = DeploymentBooking(
        booking_reference=f"T-{next(_refs):04d}",
        tenant_id=tenant_id, tenant_name=tenant_name,
        deployment_date=day, slot_number=None if emergency else slot, is_emergency=emergency,
        technology="Databricks", requester_name="R", requester_email="r@example.com",
        verifier_name="V", verifier_email="v@example.com",
        git_repository="https://git.example.com/x", implementation_summary="",
        deployment_description="", justification="j", impacted_region="APAC", status=status,
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def ncap(admin) -> int:
    return create_tenant(admin, "NCAP", "NCAP")


@pytest.fixture
def abc(admin) -> int:
    return create_tenant(admin, "ABC", "ABC")


def refs(schedules) -> list[str]:
    return [s["booking_reference"] for s in schedules]


# --------------------------------------------------------------------------- #
# Tenant lookup
# --------------------------------------------------------------------------- #


def test_partial_tenant_search_suggests_the_tenant(user, ncap, abc):
    names = [t["name"] for t in user.get("/api/tenants/lookup", params={"q": "NCA"}).json()]
    assert names == ["NCAP"]


def test_tenant_lookup_needs_sign_in(anon):
    assert anon.get("/api/tenants/lookup", params={"q": "NC"}).status_code == 401


# --------------------------------------------------------------------------- #
# Upcoming tenant schedules
# --------------------------------------------------------------------------- #


def test_upcoming_shows_only_the_tenant_and_only_weeks_it_uses(db, user, ncap, abc):
    base = week_start(today_local()) + timedelta(days=7)  # a future Sunday
    week3, week5 = base + timedelta(days=14), base + timedelta(days=28)
    n15 = insert(db, ncap, "NCAP", week3 + timedelta(days=1), 1)
    insert(db, abc, "ABC", week3 + timedelta(days=1), 2)          # same week, other tenant
    insert(db, abc, "ABC", week3 + timedelta(days=2), 1)
    n18 = insert(db, ncap, "NCAP", week3 + timedelta(days=3), 1)
    n26 = insert(db, ncap, "NCAP", week5 + timedelta(days=2), 3)
    insert(db, abc, "ABC", base + timedelta(days=1), 1)            # other tenant's lone week

    body = user.get("/api/bookings/upcoming", params={"tenant_id": ncap}).json()
    assert body["tenant_name"] == "NCAP"
    assert [w["week_start"] for w in body["weeks"]] == [week3.isoformat(), week5.isoformat()]
    assert [refs(w["schedules"]) for w in body["weeks"]] == [
        [n15.booking_reference, n18.booking_reference], [n26.booking_reference],
    ]
    assert all(s["tenant_name"] == "NCAP" for w in body["weeks"] for s in w["schedules"])
    assert body["truncated"] is False


def test_upcoming_excludes_past_and_closed_schedules(db, user, ncap):
    future = week_start(today_local()) + timedelta(days=15)
    insert(db, ncap, "NCAP", today_local() - timedelta(days=3), 1)
    insert(db, ncap, "NCAP", future, 1, status="CANCELLED")
    insert(db, ncap, "NCAP", future, 2, status="COMPLETED")
    open_one = insert(db, ncap, "NCAP", future, 3, status="IN_PROGRESS")
    body = user.get("/api/bookings/upcoming", params={"tenant_id": ncap}).json()
    assert [refs(w["schedules"]) for w in body["weeks"]] == [[open_one.booking_reference]]


def test_upcoming_orders_nearest_first_and_emergency_after_slots(db, user, ncap):
    day = week_start(today_local()) + timedelta(days=15)
    later = insert(db, ncap, "NCAP", day + timedelta(days=1), 1)
    emergency = insert(db, ncap, "NCAP", day, emergency=True)
    slot2 = insert(db, ncap, "NCAP", day, 2)
    slot1 = insert(db, ncap, "NCAP", day, 1)
    body = user.get("/api/bookings/upcoming", params={"tenant_id": ncap}).json()
    assert refs(body["weeks"][0]["schedules"]) == [
        slot1.booking_reference, slot2.booking_reference,
        emergency.booking_reference, later.booking_reference,
    ]


def test_upcoming_is_empty_not_a_list_of_empty_weeks(db, user, ncap, abc):
    insert(db, abc, "ABC", week_start(today_local()) + timedelta(days=15), 1)
    body = user.get("/api/bookings/upcoming", params={"tenant_id": ncap}).json()
    assert body["weeks"] == []


def test_upcoming_carries_release_managers_and_change_numbers(admin, user, other_user, ncap, next_monday):
    from conftest import promote_to_release_manager
    booking = create_booking(user, ncap, next_monday, 1)
    rm_id = promote_to_release_manager(admin, other_user)
    assert admin.post(f"/api/admin/bookings/{booking['id']}/assign-users", json={"user_ids": [rm_id]}).status_code == 200
    row = user.get("/api/bookings/upcoming", params={"tenant_id": ncap}).json()["weeks"][0]["schedules"][0]
    assert row["release_managers"] == [other_user.get("/api/auth/me").json()["full_name"]]
    assert row["jira_number"] == "CHG0920763"


def test_upcoming_validates_the_tenant(user, anon, ncap):
    assert user.get("/api/bookings/upcoming", params={"tenant_id": 999999}).status_code == 404
    assert anon.get("/api/bookings/upcoming", params={"tenant_id": ncap}).status_code == 401


def test_a_search_result_opens_under_the_normal_rules(db, user, other_user, ncap, next_monday):
    """Search reveals nothing the detail view would not; editing stays owner-only."""
    booking = create_booking(user, ncap, next_monday, 1)
    found = other_user.get("/api/bookings/upcoming", params={"tenant_id": ncap}).json()
    assert refs(found["weeks"][0]["schedules"]) == [booking["booking_reference"]]
    detail = other_user.get(f"/api/bookings/{booking['id']}").json()
    assert detail["can_edit"] is False and detail["can_cancel"] is False


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #


@pytest.fixture
def history(db, ncap, abc):
    today = today_local()
    return {
        "n_old": insert(db, ncap, "NCAP", today - timedelta(days=40), 1, status="COMPLETED"),
        "n_recent": insert(db, ncap, "NCAP", today - timedelta(days=5), 1, status="CANCELLED"),
        "a_recent": insert(db, abc, "ABC", today - timedelta(days=3), 1, status="COMPLETED"),
        "n_future": insert(db, ncap, "NCAP", today + timedelta(days=20), 1),
    }


def hist(client, **params):
    response = client.get("/api/bookings/history", params=params)
    assert response.status_code == 200, response.text
    return refs(response.json())


def test_history_defaults_to_the_past_newest_first(user, history):
    assert hist(user) == [history[k].booking_reference for k in ("a_recent", "n_recent", "n_old")]


def test_history_filters_combine(user, ncap, history):
    today = today_local()
    r = {k: v.booking_reference for k, v in history.items()}
    assert hist(user, tenant_id=ncap) == [r["n_recent"], r["n_old"]]
    assert hist(user, tenant_id=ncap, days=30) == [r["n_recent"]]
    assert hist(user, days=7) == [r["a_recent"], r["n_recent"]]
    window = {"date_from": (today - timedelta(days=45)).isoformat(), "date_to": (today - timedelta(days=4)).isoformat()}
    assert hist(user, **window) == [r["n_recent"], r["n_old"]]
    assert hist(user, tenant_id=ncap, **window) == [r["n_recent"], r["n_old"]]
    # An explicit range is honoured exactly, even into the future.
    ahead = {"date_from": today.isoformat(), "date_to": (today + timedelta(days=30)).isoformat()}
    assert hist(user, tenant_id=ncap, **ahead) == [r["n_future"]]


def test_days_and_a_custom_range_cannot_be_sent_together(user, admin):
    today = today_local().isoformat()
    for client, path in ((user, "/api/bookings/history"), (admin, "/api/admin/audit")):
        both = client.get(path, params={"days": 7, "date_from": today})
        assert both.status_code == 422
        assert "not both" in both.json()["detail"]
        backwards = client.get(path, params={"date_from": today, "date_to": "2000-01-01"})
        assert backwards.status_code == 422


def test_history_pages_deterministically_through_same_day_rows(db, user, ncap):
    day = today_local() - timedelta(days=2)
    rows = [insert(db, ncap, "NCAP", day, slot) for slot in (1, 2, 3, 4)]
    expected = [r.booking_reference for r in sorted(rows, key=lambda r: r.id, reverse=True)]
    first = user.get("/api/bookings/history", params={"tenant_id": ncap, "limit": 3}).json()
    last = first[-1]
    second = user.get("/api/bookings/history", params={
        "tenant_id": ncap, "limit": 3, "before_date": last["deployment_date"], "before_id": last["id"],
    }).json()
    assert refs(first) + refs(second) == expected
    assert user.get("/api/bookings/history", params={"before_id": 5}).status_code == 422


def test_history_needs_sign_in(anon):
    assert anon.get("/api/bookings/history").status_code == 401


# --------------------------------------------------------------------------- #
# Central Audit
# --------------------------------------------------------------------------- #


def audit(client, **params):
    response = client.get("/api/admin/audit", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_audit_filters_by_tenant(admin, user, ncap, abc, next_monday):
    n = create_booking(user, ncap, next_monday, 1)
    a = create_booking(user, abc, next_monday, 2)
    events = audit(admin, tenant_id=ncap)
    assert events and {e["booking_reference"] for e in events} == {n["booking_reference"]}
    assert {e["tenant_name"] for e in events} == {"NCAP"}
    assert a["booking_reference"] in {e["booking_reference"] for e in audit(admin)}


def test_audit_keeps_the_tenant_of_a_deleted_schedule(db, admin, user, ncap, next_monday):
    from app.services import booking_service
    booking = create_booking(user, ncap, next_monday, 1)
    row = db.get(DeploymentBooking, booking["id"])
    booking_service.delete_booking(db, row, booking_service.Actor(is_admin=True, admin_username="testadmin"))
    types = {e["event_type"] for e in audit(admin, tenant_id=ncap)}
    assert {"BOOKING_CREATED", "BOOKING_DELETED"} <= types


def test_audit_date_filters_use_the_business_day(db, admin, user, ncap, next_monday):
    booking = create_booking(user, ncap, next_monday, 1)
    event = db.query(BookingAudit).filter_by(booking_id=booking["id"]).first()
    # 01 Sep 2026 00:30 in Asia/Kolkata is still 31 Aug in UTC.
    event.created_at = datetime(2026, 8, 31, 19, 0)
    db.commit()
    assert [e["id"] for e in audit(admin, tenant_id=ncap, date_from="2026-09-01", date_to="2026-09-15")] == [event.id]
    assert audit(admin, tenant_id=ncap, date_from="2026-08-01", date_to="2026-08-31") == []


def test_audit_days_filter(db, admin, user, ncap, next_monday):
    booking = create_booking(user, ncap, next_monday, 1)
    # Creating a schedule writes several events (the booking and each document).
    events = db.query(BookingAudit).filter_by(booking_id=booking["id"]).all()
    ids = sorted((e.id for e in events), reverse=True)
    assert [e["id"] for e in audit(admin, tenant_id=ncap, days=30)] == ids
    for event in events:
        event.created_at = datetime.utcnow() - timedelta(days=45)
    db.commit()
    assert audit(admin, tenant_id=ncap, days=30) == []
    assert [e["id"] for e in audit(admin, tenant_id=ncap, days=90)] == ids


def test_audit_is_newest_first(admin, user, ncap, next_monday):
    create_booking(user, ncap, next_monday, 1)
    create_booking(user, ncap, next_monday, 2)
    ids = [e["id"] for e in audit(admin, tenant_id=ncap)]
    assert ids == sorted(ids, reverse=True)


def test_audit_filters_do_not_open_the_audit_to_tenants(user, anon, ncap):
    """Filtering never widens access: the Central Audit stays RM-only."""
    for params in ({}, {"tenant_id": ncap}, {"days": 30}, {"date_from": "2026-09-01"}):
        assert user.get("/api/admin/audit", params=params).status_code == 403
        assert anon.get("/api/admin/audit", params=params).status_code == 401


def test_history_schedule_number_search_combines_with_dates(db, user, ncap, abc):
    today = today_local()
    past = insert(db, ncap, "NCAP", today - timedelta(days=10), 1, status="COMPLETED")
    future = insert(db, abc, "ABC", today + timedelta(days=20), 1)
    # A number search without dates covers every date, past and future.
    assert set(hist(user, q=past.booking_reference[:2])) >= {past.booking_reference, future.booking_reference}
    assert hist(user, q=future.booking_reference) == [future.booking_reference]
    # With a Days range it is narrowed to that period.
    assert hist(user, q=future.booking_reference, days=30) == []
    assert hist(user, q=past.booking_reference, days=30) == [past.booking_reference]



def test_audit_orders_and_pages_by_timestamp_then_id(db, admin, user, ncap, next_monday):
    """A backfilled event with a lower id but newer timestamp must sort first."""
    first_booking = create_booking(user, ncap, next_monday, 1)
    second_booking = create_booking(user, ncap, next_monday + timedelta(days=1), 1)

    first_event = db.query(BookingAudit).filter_by(
        booking_id=first_booking["id"], event_type="BOOKING_CREATED"
    ).one()
    second_event = db.query(BookingAudit).filter_by(
        booking_id=second_booking["id"], event_type="BOOKING_CREATED"
    ).one()

    # first_event has the lower id, but make its event time newer.
    first_event.created_at = datetime(2026, 9, 29, 12, 0, 0)
    second_event.created_at = datetime(2026, 9, 28, 12, 0, 0)
    db.commit()

    params = {"tenant_id": ncap, "event_type": "BOOKING_CREATED", "limit": 1}
    first_page = audit(admin, **params)
    assert [row["id"] for row in first_page] == [first_event.id]

    second_page = audit(admin, **params, before_id=first_page[-1]["id"])
    assert [row["id"] for row in second_page] == [second_event.id]
