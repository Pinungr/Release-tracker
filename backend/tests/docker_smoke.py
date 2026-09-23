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
            print('PASS: production Docker startup, PostgreSQL readiness, SPA, auth, optional Jira, overnight timing, normal availability, invalid API destinations, reschedule, cancellation and audit retention.')
    finally:
        # Exact unique test container names only; never touch existing app volumes.
        for name in (app, pg):
            subprocess.run(['docker', 'rm', '-fv', name], capture_output=True)
        docker('network', 'rm', prefix)


if __name__ == '__main__':
    run()
