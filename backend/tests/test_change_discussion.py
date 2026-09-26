from datetime import timedelta
import pytest
from sqlalchemy import select
from app.models import BookingAudit, DeploymentBooking
from app.utils.dates import today_local
from conftest import create_booking, promote_to_release_manager


def test_comments_access_internal_privacy_and_audit(admin, user, other_user, anon, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    url = f"/api/bookings/{booking['id']}"
    public = user.post(url + '/comments', json={'body': 'Please review <script>alert(1)</script>'})
    assert public.status_code == 201, public.text
    assert public.json()['author_id'] == user.get('/api/auth/me').json()['id']
    assert admin.post(url + '/comments', json={'body': 'Private RM note', 'internal': True}).status_code == 201
    assert len(user.get(url + '/comments').json()) == 1
    assert len(admin.get(url + '/comments').json()) == 2
    assert 'Private RM note' not in user.get(url + '/audit').text
    assert user.post(url + '/comments', json={'body': 'secret', 'internal': True}).status_code == 403

    # Any signed-in user can read the discussion and history of any schedule,
    # but internal RM notes stay hidden from everyone who is not an RM.
    other_view = other_user.get(url + '/comments')
    assert other_view.status_code == 200
    assert [c['body'] for c in other_view.json()] == [public.json()['body']]
    other_audit = other_user.get(url + '/audit')
    assert other_audit.status_code == 200
    assert 'Private RM note' not in other_audit.text
    assert other_user.post(url + '/comments', json={'body': 'secret', 'internal': True}).status_code == 403

    # Anonymous callers still get nothing.
    for endpoint in ('/comments', '/audit'):
        assert anon.get(url + endpoint).status_code == 401
    assert anon.post(url + '/comments', json={'body': 'not yours'}).status_code == 401

    assert user.post(url + '/comments', json={'body': '  '}).status_code == 422
    assert user.post(url + '/comments', json={'body': 'x' * 5001}).status_code == 422
    newest = admin.get(url + '/comments?limit=1').json()[0]
    older = admin.get(url + f"/comments?limit=1&before_id={newest['id']}").json()
    assert older[0]['id'] == public.json()['id']
    assert user.get(url + '/audit').json()

    # A non-owner can join the conversation.
    joined = other_user.post(url + '/comments', json={'body': 'We deploy after you, same pipeline.'})
    assert joined.status_code == 201, joined.text
    assert joined.json()['author_id'] == other_user.get('/api/auth/me').json()['id']
    assert len(user.get(url + '/comments').json()) == 2


@pytest.mark.parametrize('state', ['past', 'today', 'completed', 'cancelled'])
def test_discussion_allowed_without_changing_protected_booking(admin, user, tenant, next_monday, db, state):
    booking = create_booking(user, tenant, next_monday, 1)
    row = db.get(DeploymentBooking, booking['id'])
    if state == 'past': row.deployment_date = today_local() - timedelta(days=1)
    if state == 'today': row.deployment_date = today_local()
    if state == 'completed': row.status = 'COMPLETED'
    if state == 'cancelled': row.status = 'CANCELLED'
    db.commit()
    original = (row.status, row.deployment_date, row.updated_at)
    response = user.post(f"/api/bookings/{row.id}/comments", json={'body': 'Follow-up question'})
    assert response.status_code == 201, response.text
    db.refresh(row)
    assert (row.status, row.deployment_date, row.updated_at) == original
    assert db.scalars(select(BookingAudit).where(BookingAudit.booking_id == row.id, BookingAudit.event_type == 'COMMENT_ADDED')).first()


def test_rm_can_search_assign_self_then_start(admin, user, other_user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    bid = booking['id']
    rm_id = promote_to_release_manager(admin, other_user)
    owner_id = admin.get('/api/auth/me').json()['id']

    # Type-ahead starts at two characters and only returns Release Manager members.
    assert other_user.get('/api/admin/release-managers/search?q=u').status_code == 422
    search = other_user.get('/api/admin/release-managers/search?q=us')
    assert search.status_code == 200, search.text
    assert [row['id'] for row in search.json()] == [rm_id]

    details = other_user.get(f'/api/bookings/{bid}').json()
    assert details['can_assign_self'] is True
    assert details['can_start_work'] is False

    # The protected Owner remains invalid as an assignee.
    assert other_user.post(f'/api/admin/bookings/{bid}/assign-users', json={'user_ids': [owner_id]}).status_code == 422

    assigned = other_user.post(f'/api/admin/bookings/{bid}/assign-self')
    assert assigned.status_code == 200, assigned.text
    assert [row['user_id'] for row in assigned.json()['assigned_users']] == [rm_id]
    assert assigned.json()['can_assign_self'] is False
    assert assigned.json()['can_start_work'] is True

    assert other_user.post(f'/api/bookings/{bid}/start-work', json={'change_number': 'CHG-123'}).status_code == 200
    assert other_user.post(f'/api/admin/bookings/{bid}/status', json={'status': 'COMPLETED'}).status_code == 200
    assert other_user.post(f'/api/admin/bookings/{bid}/assign-users', json={'user_ids': [rm_id]}).status_code == 400
