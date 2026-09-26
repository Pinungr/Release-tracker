"""A schedule has one RM; assigning someone else replaces the existing assignee."""
import json

import pytest
from datetime import timedelta

from sqlalchemy import select

from app.models import BookingAssignment, BookingAudit, DeploymentBooking
from conftest import create_booking, promote_to_release_manager


def assigned_ids(client, bid):
    return [row['user_id'] for row in client.get(f'/api/bookings/{bid}').json()['assigned_users']]


def test_reassignment_and_self_assignment_replace_previous_rm(admin, user, other_user, tenant, next_monday, db):
    booking = create_booking(admin, tenant, next_monday, 1)
    bid = booking['id']
    first = promote_to_release_manager(admin, user)
    second = promote_to_release_manager(admin, other_user)
    endpoint = f'/api/admin/bookings/{bid}'
    assert user.post(endpoint + '/assign-users', json={'user_ids': [first]}).status_code == 200
    reassigned = user.post(endpoint + '/assign-users', json={'user_ids': [second]})
    assert reassigned.status_code == 200, reassigned.text
    assert assigned_ids(user, bid) == [second]
    assert reassigned.json()['can_start_work'] is False
    assert reassigned.json()['can_assign_self'] is True
    assert other_user.get(f'/api/bookings/{bid}').json()['can_start_work'] is True

    # The old RM no longer has start-work permission.
    assert user.post(f'/api/bookings/{bid}/start-work', json={'change_number': 'CHG-ONE'}).status_code == 403
    self_assigned = user.post(endpoint + '/assign-self')
    assert self_assigned.status_code == 200, self_assigned.text
    assert [row['user_id'] for row in self_assigned.json()['assigned_users']] == [first]
    assert self_assigned.json()['can_start_work'] is True
    assert assigned_ids(other_user, bid) == [first]
    assert other_user.get(f'/api/bookings/{bid}').json()['can_start_work'] is False
    event = db.scalars(select(BookingAudit).where(BookingAudit.booking_id == bid, BookingAudit.event_type == 'RM_USERS_ASSIGNED').order_by(BookingAudit.id.desc())).first()
    assert json.loads(event.old_values)['assigned_user_ids'] == [second]
    assert json.loads(event.new_values)['assigned_user_ids'] == [first]


def test_multiple_and_empty_assignments_are_rejected_without_losing_current_rm(admin, user, other_user, tenant, next_monday):
    bid = create_booking(admin, tenant, next_monday, 1)['id']
    first = promote_to_release_manager(admin, user)
    second = promote_to_release_manager(admin, other_user)
    endpoint = f'/api/admin/bookings/{bid}/assign-users'
    assert admin.post(endpoint, json={'user_ids': [first]}).status_code == 200
    for ids in ([], [first, second]):
        assert admin.post(endpoint, json={'user_ids': ids}).status_code == 422
        assert assigned_ids(admin, bid) == [first]


def test_self_assignment_replaces_legacy_multiple_assignees(admin, user, other_user, tenant, next_monday, db):
    bid = create_booking(admin, tenant, next_monday, 1)['id']
    first = promote_to_release_manager(admin, user)
    second = promote_to_release_manager(admin, other_user)
    db.add_all([BookingAssignment(booking_id=bid, user_id=first), BookingAssignment(booking_id=bid, user_id=second)])
    db.commit()
    assert user.get(f'/api/bookings/{bid}').json()['can_assign_self'] is True
    response = user.post(f'/api/admin/bookings/{bid}/assign-self')
    assert response.status_code == 200, response.text
    assert assigned_ids(user, bid) == [first]


@pytest.mark.parametrize('state', ['today', 'past', 'completed', 'cancelled'])
def test_reassignment_keeps_protected_records_unchanged(admin, user, other_user, tenant, next_monday, db, state):
    from app.utils.dates import today_local
    bid = create_booking(admin, tenant, next_monday, 1)['id']
    first = promote_to_release_manager(admin, user)
    second = promote_to_release_manager(admin, other_user)
    endpoint = f'/api/admin/bookings/{bid}'
    assert user.post(endpoint + '/assign-users', json={'user_ids': [first]}).status_code == 200
    row = db.get(DeploymentBooking, bid)
    if state in {'today', 'past'}:
        row.deployment_date = today_local() - timedelta(days=state == 'past')
    else:
        row.status = state.upper()
    db.commit()
    assert other_user.post(endpoint + '/assign-self').status_code in {400, 423}
    assert other_user.post(endpoint + '/assign-users', json={'user_ids': [second]}).status_code in {400, 423}
    assert assigned_ids(admin, bid) == [first]


def test_invalid_rm_and_owner_do_not_replace_current_assignee(admin, user, other_user, tenant, next_monday):
    bid = create_booking(admin, tenant, next_monday, 1)['id']
    first = promote_to_release_manager(admin, user)
    endpoint = f'/api/admin/bookings/{bid}'
    assert user.post(endpoint + '/assign-users', json={'user_ids': [first]}).status_code == 200
    for client in [admin, other_user]:
        uid = client.get('/api/auth/me').json()['id']
        assert user.post(endpoint + '/assign-users', json={'user_ids': [uid]}).status_code == 422
        assert client.post(endpoint + '/assign-self').status_code == 403
        assert assigned_ids(admin, bid) == [first]
