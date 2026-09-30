"""Run against the built image and an isolated, disposable PostgreSQL container.

From the repository root:
  docker build -t pds-scheduler-validation:local .
  python backend/tests/docker_smoke.py
No existing application containers, volumes or credentials are used.
"""
import json
import secrets
import subprocess
import time
from datetime import date, timedelta

import httpx


def docker(*args):
    result = subprocess.run(['docker', *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'Docker {args[0]} failed: {result.stderr}')
    return result.stdout.strip()


def run():
    prefix = 'pds-smoke-' + secrets.token_hex(4)
    pg, app = prefix + '-pg', prefix + '-app'
    password = secrets.token_urlsafe(32)
    docker('network', 'create', prefix)
    try:
        docker('run', '-d', '--name', pg, '--network', prefix,
               '--tmpfs', '/var/lib/postgresql/data', '-e', 'POSTGRES_DB=scheduler',
               '-e', 'POSTGRES_USER=scheduler', '-e', f'POSTGRES_PASSWORD={password}',
               'postgres:16-alpine')
        for _ in range(60):
            ready = subprocess.run(['docker', 'exec', pg, 'pg_isready', '-U', 'scheduler'], capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError('Disposable PostgreSQL did not become ready')
        docker('run', '-d', '--name', app, '--network', prefix, '-p', '127.0.0.1::8000',
               '-e', 'ENVIRONMENT=production', '-e', f'JWT_SECRET={secrets.token_urlsafe(48)}',
               '-e', f'DATABASE_URL=postgresql+psycopg://scheduler:{password}@{pg}:5432/scheduler',
               '-e', 'BOOTSTRAP_ADMIN_USERNAME=smokeadmin', '-e', f'BOOTSTRAP_ADMIN_PASSWORD={password}',
               '-e', 'STORAGE_DIR=/tmp/pds-storage', '-e', 'FRONTEND_DIST=/app/frontend/dist',
               'pds-scheduler-validation:local')
        port = json.loads(docker('inspect', app))[0]['NetworkSettings']['Ports']['8000/tcp'][0]['HostPort']
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=15) as client:
            for _ in range(60):
                try:
                    if client.get('/health/ready').status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            else:
                raise RuntimeError('Disposable production application did not become ready')
            assert client.get('/').status_code == 200
            auth = client.post('/api/auth/login', json={'username_or_email': 'smokeadmin', 'password': password})
            assert auth.status_code == 200, auth.text
            client.headers['Authorization'] = 'Bearer ' + auth.json()['access_token']
            tenant = client.post('/api/admin/tenants', json={'name': 'Smoke tenant', 'tenant_code': 'SMOKE'}).json()['id']
            today = date.fromisoformat(client.get('/api/schedule').json()['today'])
            source = today - timedelta(days=(today.weekday() + 1) % 7) + timedelta(days=21)
            payload = {
                'tenant_id': tenant, 'deployment_date': str(source), 'slot_number': 1,
                'technology': 'Databricks',
                'verifier_name': 'Smoke verifier', 'git_repository': 'https://example.com/repo',
                'justification': 'Integration validation', 'impacted_region': 'APAC',
            }
            files = [(f'document_{category}', ('evidence.txt', b'smoke evidence')) for category in
                     ('TEST_RESULTS', 'INVENTORY', 'IMPLEMENTATION_PLAN', 'VALIDATION_PLAN', 'DBA_SCRIPT')]
            response = client.post('/api/bookings', data={'payload': json.dumps(payload)}, files=files)
            assert response.status_code == 201, response.text
            booking = response.json()['booking']
            assert booking['jira_number'] is None and booking['slot_time'] == '09:00 PM - 05:00 AM'
            path = f"/api/bookings/{booking['id']}"
            # Admin mutation responses must preserve the signed-in actor's permissions.
            move = client.post(f"/api/admin/bookings/{booking['id']}/move", json={
                'deployment_date': str(source + timedelta(days=2)), 'slot_number': 2,
            })
            assert move.status_code == 200, move.text
            assert move.json()['can_edit'] and move.json()['can_manage_attachments']
            status = client.post(f"/api/admin/bookings/{booking['id']}/status", json={'status': 'BOOKED'})
            assert status.status_code == 200 and status.json()['can_assign_rm'], status.text
            holiday = source + timedelta(days=1)
            assert client.post('/api/admin/holidays', json={'holiday_date': str(holiday), 'name': 'Smoke holiday', 'is_full_day': True}).status_code == 201
            options = client.get(path + '/reschedule-options?limit=100').json()
            assert options
            keys = [(date.fromisoformat(o['deployment_date']), o['slot_number']) for o in options]
            assert keys == sorted(keys)
            assert all(day > today and day != holiday and day.weekday() not in (4, 5) for day, _ in keys)
            for target in (source + timedelta(days=5), source + timedelta(days=6), holiday, today):
                rejected = client.post(path + '/reschedule', json={'deployment_date': str(target), 'slot_number': 1})
                assert rejected.status_code in (400, 423), rejected.text
            target = options[0]
            moved = client.post(path + '/reschedule', json={'deployment_date': target['deployment_date'], 'slot_number': target['slot_number']})
            assert moved.status_code == 200, moved.text
            assert client.request('DELETE', path, json={}).status_code == 200
            retained = client.get(path).json()
            assert retained['status'] == 'CANCELLED' and len(retained['attachments']) == 5
            events = client.get(f"/api/admin/audit?booking_id={booking['id']}").json()
            assert {'BOOKING_CREATED', 'BOOKING_RESCHEDULED', 'BOOKING_CANCELLED'} <= {e['event_type'] for e in events}
            registered = client.post('/api/auth/register', json={
                'full_name': 'Smoke RM', 'username': 'smokerm', 'email': 'smokerm@example.com',
                'password': password, 'confirm_password': password,
            })
            assert registered.status_code == 201, registered.text
            user_id = registered.json()['user']['id']
            for role in ('ADMIN', 'TENANT_USER'):
                changed = client.patch(f'/api/admin/users/{user_id}/role', json={'role': role})
                assert changed.status_code == 200, changed.text
            role_events = client.get('/api/admin/audit', params={'event_type': 'USER_ROLE_UPDATED'}).json()
            assert len(role_events) == 2
            assert role_events[0]['old_values'] == {'role': 'ADMIN'}
            assert role_events[0]['new_values'] == {'role': 'TENANT_USER'}
            assert role_events[1]['new_values'] == {'role': 'ADMIN'}

            # Seed a booking made earlier, then follow up through public APIs.
            historical = client.post('/api/bookings', data={'payload': json.dumps(payload)}, files=files)
            assert historical.status_code == 201, historical.text
            historical_id = historical.json()['booking']['id']
            seed_history = (
                'from app.database import SessionLocal; '
                'from app.models import DeploymentBooking; '
                'from app.utils.dates import today_local; '
                'from datetime import timedelta; '
                'db=SessionLocal(); '
                f'row=db.get(DeploymentBooking, {historical_id}); '
                'row.deployment_date=today_local()-timedelta(days=7); '
                'db.commit(); db.close()'
            )
            docker('exec', app, 'python', '-c', seed_history)
            history_path = f'/api/bookings/{historical_id}'
            history_day = str(today - timedelta(days=7))
            unlocked = client.post('/api/admin/lock-overrides', json={'override_date': history_day})
            assert unlocked.status_code == 201, unlocked.text
            detail = client.get(history_path).json()
            assert detail['can_upload_attachments'] and detail['attachments_add_only'] and detail['can_close']
            assert not detail['can_edit'] and not detail['can_manage_attachments']
            appended = client.post(history_path + '/attachments', data={'category': 'SUPPORTING_DOCUMENTS'},
                                   files=[('file', ('extra.txt', b'follow-up evidence'))])
            assert appended.status_code == 200 and len(appended.json()['attachments']) == 6, appended.text
            replaced = client.post(history_path + '/attachments', data={'category': 'TEST_RESULTS'},
                                   files=[('file', ('replacement.txt', b'must not replace'))])
            assert replaced.status_code == 423, replaced.text
            assert client.request('DELETE', history_path, json={}).status_code == 423
            assert client.post(history_path + '/comments', json={'body': 'Production follow-up.'}).status_code == 201
            assert client.delete(f'/api/admin/lock-overrides/{history_day}').status_code == 204
            closed = client.post(f'/api/admin/bookings/{historical_id}/status', json={'status': 'COMPLETED'})
            assert closed.status_code == 200 and closed.json()['status'] == 'COMPLETED', closed.text
            assert closed.json()['change_number'] is None and closed.json()['work_started_at'] is None
            assert len(closed.json()['attachments']) == 6
            assert closed.json()['can_reopen']
            reopened = client.post(f'/api/admin/bookings/{historical_id}/reopen')
            assert reopened.status_code == 200 and reopened.json()['status'] == 'BOOKED', reopened.text
            assert not reopened.json()['can_edit'] and not reopened.json()['can_reopen']
            assert not reopened.json()['can_upload_attachments']
            assert len(reopened.json()['attachments']) == 6
            assert reopened.json()['deployment_date'] == history_day
            assert client.request('DELETE', history_path, json={}).status_code == 423
            assert client.post(f'/api/admin/bookings/{historical_id}/reopen').status_code == 400
            history_events = client.get('/api/admin/audit', params={'booking_id': historical_id, 'event_type': 'BOOKING_REOPENED'}).json()
            assert len(history_events) == 1
            assert history_events[0]['old_values']['status'] == 'COMPLETED'
            assert history_events[0]['new_values']['status'] == 'BOOKED'

            # Verify the timestamp/id cursor against production PostgreSQL too.
            expected = [event['id'] for event in client.get('/api/admin/audit', params={'limit': 500}).json()]
            seen, cursor = [], None
            for _ in range(len(expected) + 1):
                params = {'limit': 2}
                if cursor is not None:
                    params['before_id'] = cursor
                page = client.get('/api/admin/audit', params=params).json()
                if not page:
                    break
                seen.extend(event['id'] for event in page)
                cursor = page[-1]['id']
            assert seen == expected, 'Audit pagination skipped or repeated events'
            print('PASS: production Docker startup, PostgreSQL readiness, SPA, auth, optional Jira/verifier email, overnight timing, normal availability, invalid API destinations, admin response permissions, reschedule, cancellation, role-change audit, recent append-only unlocks, protected scheduling, historical closure/reopening and complete audit pagination.')
    except Exception:
        logs = subprocess.run(['docker', 'logs', '--tail', '100', app], capture_output=True, text=True)
        print((logs.stdout + logs.stderr).replace(password, '<redacted>'))
        raise
    finally:
        # Exact unique test container names only; never touch existing app volumes.
        for name in (app, pg):
            subprocess.run(['docker', 'rm', '-fv', name], capture_output=True)
        docker('network', 'rm', prefix)


if __name__ == '__main__':
    run()
