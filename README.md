# Production Deployment Scheduler

A web replacement for the weekly production deployment scheduling spreadsheet.
People sign in, pick a **tenant**, and reserve a production deployment slot for
the week. Administrators manage users, tenants, holidays, slots and emergency
changes.

---

## 1. Architecture

A **single monolithic application**: one process, one port, one origin. The
FastAPI app owns the database, the business rules, the REST API, the uploaded
documents *and* the compiled React frontend. PostgreSQL runs beside it in
Docker and is never exposed to the host.

```
                         USERS
                           │
                     Login / Sign up
                           │
                           ▼
                     FastAPI Auth
                           │
                           ▼
                   PostgreSQL  users
                           │
                         role
                  ┌────────┴────────┐
                  │                 │
            TENANT_USER           ADMIN
                  │                 │
                  └────────┬────────┘
                           │
                   Release Scheduler
                           │
                     Schedule a CR
                           │
                     Select Tenant
                           │
                           ▼
                    DeploymentBooking
                     /            \
          created_by_user_id     tenant_id
```

**A user is a person; a tenant is chosen per change record.** One person can
schedule changes for many tenants. There is no permanent user-to-tenant
assignment anywhere in the system.

```
Pinaki
 ├── CR1 → Tenant A
 ├── CR2 → Tenant B
 └── CR3 → Tenant C
```

### Request routing inside the one process

| Request | Handled by |
| --- | --- |
| `/api/...` | API routers; unknown paths return a JSON 404 |
| `/health`, `/health/ready` | liveness and readiness probes (readiness pings the database) |
| `/docs`, `/redoc`, `/openapi.json` | FastAPI's own docs |
| an existing file under `frontend/dist` | served directly (hashed assets cached for a year; `index.html` never cached) |
| anything else | `index.html`, so React handles the client-side route |

Because the UI is served from the origin it then calls, no cross-origin request
is ever made and CORS is not involved.

### Project layout

```
production-deployment-scheduler/
├── backend/
│   ├── app/
│   │   ├── __main__.py          `python -m app` — starts the whole thing
│   │   ├── main.py              app assembly, middleware, health, SPA mount
│   │   ├── web.py               serves the compiled SPA
│   │   ├── config.py            env-driven settings
│   │   ├── database.py          SQLAlchemy engine/session
│   │   ├── models/              User, Tenant, DeploymentBooking, BookingAttachment,
│   │   │                        Holiday, DeploymentSlotConfiguration,
│   │   │                        DailySlotCapacity, ApplicationSetting, BookingAudit
│   │   ├── schemas/             Pydantic request/response models
│   │   ├── api/                 auth, schedule, bookings, attachments, tenants, admin
│   │   ├── services/            business rules (the source of truth)
│   │   ├── security/            hashing, JWT, auth dependencies, rate limiting
│   │   ├── utils/               date/timezone helpers, safe file storage
│   │   └── seed.py              demo data
│   ├── tests/                   backend regression tests
│   └── requirements.txt
├── frontend/                    React + TypeScript + Vite + Tailwind CSS v4
│   └── src/
│       ├── components/          SignInScreen, AppHeader, WeekNavigator,
│       │                        ScheduleSummary, WeeklySchedule, DaySchedule,
│       │                        DeploymentSlot, BookingDrawer, BookingForm,
│       │                        BookingDetailsDrawer, DocumentUploader,
│       │                        DocumentReadiness, ProfileModal, AdminPanel,
│       │                        AdminUserManager, AdminTenantManager,
│       │                        AuditHistory, Drawer, Modal, Toast, Icons
│       ├── hooks/               useAuthSession, useSchedule
│       ├── services/api.ts      REST client
│       ├── types/               API types
│       └── utils/               date + formatting helpers
├── Dockerfile                   multi-stage: build the SPA, then run the app
├── docker-compose.yml           app + postgres, both with persistent volumes
├── .env.example
└── README.md
```

**Architectural rule:** the backend is the source of truth. Authentication,
ownership, the tenant weekly limit, the date-only deployment freeze, holiday blocking and
emergency-change access are all revalidated in the API on every write. The
frontend's copies exist only for immediate feedback.

---

## 2. Roles and access

| | TENANT_USER | ADMIN |
| --- | --- | --- |
| Sign up | self-service | promoted by the owner |
| See the weekly board | ✅ | ✅ |
| Schedule a normal change | ✅ | ✅ |
| See / edit / cancel a change | own changes; assigned RM users can view and start work | any |
| Upload/delete documents | own editable changes | editable changes |
| Download documents | own changes and assigned RM changes, including read-only records | any |
| Emergency changes | view only | create, edit, cancel |
| Exceed the tenant weekly limit | ❌ | ✅ automatic administrator bypass, audited |
| Book/edit/cancel inside the automatic protected date window | ❌ | ❌ |
| Users, tenants, holidays, slots, settings, audit | ❌ | ✅ |

Everyone uses **one login**. There is no separate administrator sign-in and no
separate administrator table — `users.role` is the only thing that grants
administrator access, and it is re-read from the database on every request, so
promoting, demoting or deactivating an account takes effect immediately.

### The owner account

One administrator is additionally flagged as the **owner** (`users.is_owner`).
It is the bootstrap administrator, created on first start, and there is no API
that grants the flag, so the tier cannot be escalated into.

Administrators manage tenant users. Everything that targets an account which is
*already* an administrator is reserved for the owner:

| Action | ADMIN | OWNER |
| --- | --- | --- |
| Reset a **tenant user's** password, activate/deactivate them | ✅ | ✅ |
| Promote a tenant user to ADMIN | ❌ | ✅ |
| Demote / deactivate / reset the password of **another ADMIN** | ❌ | ✅ |
| Act on the **owner** account | ❌ | ❌ (self-service only) |
| Act on **your own** account via Admin → Users | ❌ | ❌ (self-service only) |

Without this separation a single promotion would be enough to take over the
installation: the promoted account could reset every other administrator's
password — including the owner's — and lock everyone else out. The owner can
always demote a rogue administrator, and the flag guarantees a recovery account
always exists.

---

## 3. Business rules

| Rule | Default | Configurable in |
| --- | --- | --- |
| Normal deployment slots per day | 4 | Admin → General / Slots; add or remove slots on one date from the board |
| Emergency changes | unlimited per date, admin only | Admin → General |
| Normal changes per **tenant** per week | 2 | Admin → General |
| Booking/edit freeze | Today + next 2 valid deployment dates | Admin → General; manual per-slot freeze also available |
| Maximum upload size | 20 MB per file | Admin → General |
| Mandatory documents | Test result, inventory, implementation document, validation plan, DBA script | Admin → Documents |
| Working week | Sunday–Thursday for normal deployment slots; Friday/Saturday skipped | fixed |
| Timezone | Asia/Kolkata | `TIMEZONE` |

**The weekly limit is per tenant, not per user.** If user A and user B each
schedule one change for Tenant X in the same week, Tenant X is at 2/2 and
nobody may add a third — but both users still have the full quota available
for any other tenant.

**Emergency changes are a queue, not a slot.** Any number can sit on the same
date, they carry no slot number, they never consume normal deployment capacity,
and they never count against a tenant's weekly quota.

**Normal availability is identical for Admin and users.** The board, counters and
Next Available reschedule picker exclude Friday/Saturday, full-day holidays,
past/current/protected dates, manual freezes, disabled or missing slots, slots
above the date capacity, and occupied slots. Results are ordered by date and
slot number. The backend revalidates the destination on every reschedule POST.
Tenant weekly limits still apply to normal users; Admin weekly-limit bypasses
remain audited.

**Manual Admin overrides are explicit.** For exceptional API operations, normal
booking creation/update or `/admin/bookings/{id}/move` requires
`manual_override: true` and a non-empty `override_reason` to bypass weekends,
holidays, manual freezes or disabled capacity. Normal rescheduling never uses
this override. Missing and occupied slots cannot be overridden. The separate
Admin emergency queue remains available on weekends and holidays. All booking
operations, including emergency operations, RM assignment/work, status changes
and attachments, respect past/current/automatic date protection.

**Jira is optional by default** (`jira_required_at_booking: false` in Admin
Booking Rules). Supply it at booking if available; an administrator can require
it through Booking Rules. Change Number is separate and supplied later when an
assigned RM starts work. All normal slots default to **9:00 PM to 5:00 AM the
following morning**, using the configured timezone. Slot times remain editable
in Admin settings.

Capacity responses separate `configured_slots_total` (the configured date limit, independent of disabled
or missing slot rows) from `regular_slots_available` (currently free and
bookable). `regular_slots_total` counts booked rows plus currently bookable free
rows, including retained bookings on closed dates. Tenant quotas are enforced
when choosing a booking destination; board counters describe slot capacity.

```
DAY
├── Normal Slot 1   9:00 PM - 5:00 AM
├── Normal Slot 2   9:00 PM - 5:00 AM
├── Normal Slot 3   9:00 PM - 5:00 AM
├── Normal Slot 4   9:00 PM - 5:00 AM
│
└── Emergency CR queue        (admin only)
      ├── Emergency CR 1
      ├── Emergency CR 2
      └── + Add emergency CR
```

---

## 4. Requirements

* **Docker Desktop** (Windows/macOS) or Docker Engine + Compose plugin (Linux).
* For local development without Docker: Python 3.11+ and Node.js 20+.

---

## 5. Configuration

```bash
cp .env.example .env
```

Edit `.env` — at minimum set `JWT_SECRET`, `POSTGRES_PASSWORD` and
`BOOTSTRAP_ADMIN_PASSWORD` before exposing the app to anyone.

```ini
ENVIRONMENT=production
POSTGRES_DB=scheduler
POSTGRES_USER=scheduler
POSTGRES_PASSWORD=<strong password>
JWT_SECRET=<long random string>
BOOTSTRAP_ADMIN_USERNAME=admin
BOOTSTRAP_ADMIN_PASSWORD=<strong password>
TIMEZONE=Asia/Kolkata
CORS_ORIGINS=
```

Generate a secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

With `ENVIRONMENT=production` the app refuses to start while `JWT_SECRET` or
`BOOTSTRAP_ADMIN_PASSWORD` are still at their placeholder values.


### Database migrations

Database schema evolution is managed with **Alembic**. Startup applies the
existing migration chain through `20260922_0004` before creating the default
slots and bootstrap administrator. This scheduling fix adds no migrations and
does not require resetting the database. Preserve existing data and migration
history; future schema changes should use a new revision.

Manual commands from `backend/`:

```bash
alembic current
alembic upgrade head
```

### Bootstrap administrator

On first start the app creates **one** administrator in the ordinary `users`
table from `BOOTSTRAP_ADMIN_USERNAME` / `BOOTSTRAP_ADMIN_PASSWORD`:

```
IF that username does not exist:
    create the user, hash the password with bcrypt, role = ADMIN
ELSE:
    do nothing
```

The password is hashed immediately and never stored in clear text. An existing
account is left untouched, so restarting never resets a password somebody has
already changed.

**POC default: `admin` / `admin2024`. Change it before any real use.**

When an administrator resets a user's password, the account is marked
`must_change_password`. The temporary password can authenticate only to the
password-change/logout endpoints; scheduler and administration APIs remain
blocked until the user sets a new password.


---

## 6. Running with Docker

### Windows (Docker Desktop)

Start Docker Desktop, then from the project folder in PowerShell:

```powershell
docker compose up -d --build
```

### Linux

```bash
docker compose up -d --build
```

Open <http://localhost:8000>.

> **Windows:** if `docker compose up` fails with *"ports are not available …
> An attempt was made to access a socket in a way forbidden by its access
> permissions"*, port 8000 sits inside a range Windows reserves for
> Hyper-V/WinNAT — nothing is actually using it. List the reserved ranges with
> `netsh interface ipv4 show excludedportrange protocol=tcp`, then publish on a
> free port instead: `APP_PORT=9000 docker compose up -d` (or set `APP_PORT` in
> `.env`). The app still listens on 8000 inside the container.

PostgreSQL runs on the Compose network as `postgres:5432`. It is also bound
only to localhost on the host at `127.0.0.1:15432`, and is not exposed to external
network interfaces.

Useful commands:

```bash
docker compose logs -f app
```

```bash
docker compose ps
```

```bash
docker compose down
```

`docker compose down` keeps the `postgres-data` and `app-storage` volumes.
Use `docker compose down -v` only when you intend to destroy all data.

### Audit retention and exceptional cleanup

Use cancellation for normal removal: the booking, documents, assignments and
audit history remain. Rescheduling retains the same booking identity and all
history. The Admin UI offers cancellation instead of permanent deletion.
`DELETE /api/admin/bookings/{id}?confirmation=<exact-booking-reference>` is
restricted to `ENVIRONMENT=development` and unprotected future records. It
irreversibly deletes the record and document files but retains detached audit
events by booking reference, plus a deletion snapshot. The exact reference is
required as explicit confirmation. Production rejects this cleanup endpoint.

### Health checks

```bash
curl http://localhost:8000/health
```

```bash
curl http://localhost:8000/health/ready
```

`/health/ready` runs a real query against PostgreSQL and returns 503 when the
database is unreachable; Compose uses it as the app container's healthcheck.

---

### Environment configuration

Docker Compose interpolates the project-root `.env` (or an explicit
`docker compose --env-file ...` file). Variables in the invoking shell take
precedence. Compose passes its `environment:` values to the container;
`backend/.env` does not override those process variables.

For local Python execution, the application loads root `.env` first and
`backend/.env` second, so the backend file overrides the root file only for
values absent from the process environment. Use a local `DATABASE_URL` such as
`postgresql+psycopg://scheduler:<password>@localhost:15432/scheduler` when using
the Compose database from a host Python process. Inside Compose, use
`postgres:5432`. Keep real secrets in untracked environment files.

`POSTGRES_IMAGE` defaults to `postgres:16-alpine`. Set it in the root `.env` to
an approved mirror, for example `<artifactory-registry>/postgres:16-alpine`.
Production startup rejects both known JWT placeholders
(`change-me-in-production`, `replace-with-a-long-random-string`) and secrets
shorter than 32 characters. Generate a unique random secret before deploying.
Development supports the sample placeholders for local startup.

## 7. Local development without Docker

You need a PostgreSQL to point at, or SQLite for a quick local run.

```bash
cd backend && python -m venv .venv
```

```bash
cd backend && .venv/Scripts/python -m pip install -r requirements.txt
```

(macOS/Linux: `.venv/bin/python` throughout.)

```bash
cd frontend && npm ci && npm run build
```

```bash
cd backend && .venv/Scripts/python -m app
```

The schema, the default four-slot grid and the bootstrap administrator are
created automatically on first start.

For hot-reloading React work, run Vite alongside it and use
<http://localhost:5173>; Vite proxies `/api` to port 8000, so the browser still
talks to a single origin:

```bash
cd frontend && npm run dev
```

### Demo data

```bash
cd backend && .venv/Scripts/python -m app.seed
```

Creates three tenants, a holiday, three normal changes across three different
tenants owned by one person, and one emergency change.
Demo sign-in: **`demo.user` / `DemoPass!2026`**.

---

## 8. Using the application

**As a tenant user**

1. Open the URL and **Sign up** (full name, username, email, password,
   confirm password), then sign in. New accounts are always `TENANT_USER`.
2. Navigate with **Previous week / Next week / Today**.
3. Click **Book slot** on a free slot. Choose the **tenant** in the drawer —
   this is per change record, not per account. **Jira No. can be optional or required from Admin → General**; Jira URL is stored separately. **Justification** and **Impacted region** are required on every change record
   (the separate *Business justification* remains emergency-only). Requester email,
   verifier email, implementation summary and deployment description are optional.
4. Before confirming the slot, attach every required deployment document. The booking is created only after the mandatory files are accepted by the backend.
5. Your own changes are badged **My booking**; the **My changes** card filters
   the board to them.
6. Past dates and the current date are permanently read-only for everyone, including administrators. Admin → General controls how many **upcoming valid deployment dates** are also automatically frozen; Friday/Saturday and full-day holidays are skipped while counting. Those automatic date freezes cannot be bypassed by Admin. Manual per-slot freezes remain available for normal users, with Admin override outside the automatic protected-date window.
7. If an administrator assigns you to a booked change as an RM user, it appears in **My changes**. You can open it and **Start work** by entering the separate **Change No.**; assignment does not give you ownership/edit/cancel rights.
8. **Profile** shows your account and lets you change your password.

**As an administrator**

1. Sign in with the same form; the header gains **Admin controls**.
2. *Users* — activate/deactivate and reset a password for **tenant users**.
   You never see an existing password or hash.
   Administrators are deliberately protected from each other: only the owner
   can promote, demote, deactivate or reset an administrator, nobody (not even
   the owner) can target the owner account through this screen, and no
   administrator can act on their own account here — change your own password
   from your profile. Without this, a single promotion would let anyone reset
   every other administrator's password and lock the installation. The last
   active administrator still cannot be demoted or deactivated.
3. *Tenants* — add, edit, activate, deactivate. Only active tenants appear in
   the scheduling form.
4. *General* — slots per day, weekly limit and upload size.
   *Slots* — names and times of the normal slots.
   *Holidays* — full or partial day, emergency allowed or not.
   *Documents* — which categories are mandatory.
   *Bookings* - open, assign one or more RM users, complete or cancel while editable.
   Permanent deletion removes the booking/files but **retains its audit history**.
   *Audit* — every create, edit, assignment, work start, move, cancel, document change, override and hard delete.
5. **Add emergency CR** on any day's emergency queue. The form additionally
   requires an emergency reason and business justification.
6. Administrator policy bypasses are recorded in the audit trail. The generated PDS reference identifies the booking; Jira No. is optional by default and the separate Change No. is supplied later by an assigned RM user when work starts.

---

## 9. Documents

Six categories, five mandatory by default:

| Category | Default | Files |
| --- | --- | --- |
| Non-Production Test Result | required | one |
| Inventory File | required | one |
| Implementation Document | required | one |
| Validation Plan | required | one |
| DBA Script | required | one |
| Supporting Documents | optional | many |

Accepted types: `.pdf .doc .docx .xls .xlsx .csv .txt .zip .sql .png .jpg .jpeg`

Files live outside the database:

```
storage/deployments/<booking-id>/
    test-results/        inventory/           implementation-plan/
    validation-plan/     dba-script/          supporting-documents/
```

Stored filenames are freshly generated UUIDs plus a whitelisted extension; the
uploaded name is kept only as a display label. Files are never executed, never
served inline, and every resolved path is re-checked against the storage root.
Upload and download require the authenticated owner or an administrator.

---

## 10. Database administration

The database is PostgreSQL inside the Compose network.

```bash
docker compose exec postgres psql -U scheduler -d scheduler
```

```bash
docker compose exec postgres psql -U scheduler -d scheduler -c "\dt"
```

Tables: `users`, `tenants`, `deployment_bookings`, `booking_attachments`,
`holidays`, `slot_configurations`, `daily_slot_capacity`,
`application_settings`, `booking_audit`.

The schema is created from the SQLAlchemy models on start-up. This POC has no
migration tooling: after a model change, recreate the database
(`docker compose down -v && docker compose up -d --build`).

---

## 11. Persistent storage and backup

Two named volumes hold everything that matters:

| Volume | Contents |
| --- | --- |
| `postgres-data` | the PostgreSQL database |
| `app-storage` | uploaded deployment documents |

Back both up in the same window so records and files stay consistent.

```bash
docker compose exec -T postgres pg_dump -U scheduler scheduler > backup/scheduler-$(date +%F).sql
```

```bash
docker run --rm -v pds_app-storage:/data -v "$PWD/backup:/backup" alpine tar -czf /backup/documents-$(date +%F).tar.gz -C /data .
```

Restore by stopping the stack, restoring the volumes, and starting again. Check
your actual volume names with `docker volume ls` — Compose prefixes them with
the project directory name.

---

## 12. Testing

```bash
cd backend && .venv/Scripts/python -m pytest
```

**131 tests, all passing.** They cover the rules that matter:

* sign-up creates a TENANT_USER and can never self-grant ADMIN
* login by username or email; identical message for unknown user and wrong
  password; rate limiting; passwords stored bcrypt-hashed
* the administrator signs in through the same login from the same users table
* the bootstrap administrator is not reset on restart
* promotion, demotion and deactivation take effect on the very next request
* admin routes reject anonymous (401) and tenant users (403)
* the board, tenant list and every booking route require authentication
* a user can schedule for several tenants; tenants come only from the master
  and scheduling never creates one as a side effect
* ownership: the owner may read/edit/cancel; another user gets 403; an admin
  may act on anything
* 2 normal changes per tenant per week — shared across users, independent per
  tenant, resets weekly, freed by cancellation, overridable by an admin *with
  an audited reason*
* past/current dates plus the configured upcoming valid deployment dates are hard-frozen for booking/edit/cancel for everyone, including administrators; separate manual slot freezes still block normal users and remain admin-overridable outside that automatic date window
* multiple emergency changes on one date, admin-only, consuming neither slots
  nor quota; tenant users are refused
* holidays block normal slots and can keep or close the emergency queue;
  partial holidays stay open; an administrator can add or remove normal slots
  on a single date without affecting any other
* document readiness, configurable mandatory set, file-type and size limits,
  filename sanitisation, and owner/admin-only download
* concurrency: eight simultaneous requests for one slot leave exactly one
  winner; five simultaneous emergency changes on one date all succeed
* the monolith's serving layer, including traversal attempts under `/assets`

SQLite backs the test suite on purpose — it gives each test a fresh isolated
schema in milliseconds. Production runs on PostgreSQL; nothing in the
application depends on which of the two sits behind SQLAlchemy.

```bash
cd frontend && npm run typecheck
```

```bash
cd frontend && npm run build
```

---

Frontend regression checks:

```bash
cd frontend
npm test
npm run build
```

The backend suite runs from `backend/` with `python -m pytest -q`. Set
`FRONTEND_DIST` to the absolute `frontend/dist` path to include SPA serving tests
when a local environment file points it elsewhere. For a disposable PostgreSQL
integration check, from the repository root run:

```bash
docker build -t pds-scheduler-validation:local .
python backend/tests/docker_smoke.py
```

The smoke check creates and removes its own uniquely named containers/network;
it does not use existing application data or credentials.

## 13. Security notes

* **Passwords are hashed** with bcrypt (cost 12) over a SHA-256 pre-hash, so
  nothing is truncated at bcrypt's 72-byte limit. A password is never stored,
  logged, returned by an API, or written to the audit trail — administrators
  can set a new one but can never see an existing one.
* **Sessions** are HS256 JWTs in `Authorization: Bearer`. The token carries
  identity only; the **role is read from the database on every request**, so
  there is exactly one source of truth for authorization. No cookies are
  issued, so there is no CSRF surface. Logout revokes the token id server-side.
* **Ownership** is `created_by_user_id` versus the authenticated caller.
  Assigned RM users additionally have read/download/start-work access; assignment
  does not grant booking edit/cancel or document upload/delete permissions.
  All mutations respect date protection.
* **Authentication is checked before authorization**, so an anonymous caller
  always gets 401 and never a misleading 403.
* **Rate limiting** protects sign-up, login and password change.
* **Concurrency** is handled by a partial unique index on
  `(deployment_date, slot_number)` for non-cancelled, non-emergency rows — not
  by a check-then-insert — so a race can only ever produce one winner.
* **Self-lockout protection**: the last active administrator cannot be demoted
  or deactivated.
* PostgreSQL is bound only to host localhost (`127.0.0.1:15432`); the app talks to it over the
  Compose network only.
* Unhandled exceptions return a generic message; stack traces and SQL stay in
  the server log.
* Responses carry `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`
  and `Referrer-Policy: no-referrer`.

The container runs a **single worker** on purpose: the login rate limiter and
the logout revocation list are process-local, so extra workers would weaken
both. Move them to Redis before scaling out.

### Future LDAP

Authentication is already separated from authorization: `api/auth.py` verifies
a credential and issues a token, while `security/deps.py` resolves the role
from the `users` table. Swapping the credential check for LDAP later means
touching the first of those only — PostgreSQL stays the authority for roles.
No unused LDAP scaffolding ships today.

---

## 14. API overview

All routes are under `/api` on the same origin as the UI. Interactive
documentation: `/docs`.

### Authentication

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/auth/register` | Self-service sign-up (always TENANT_USER) |
| `POST` | `/auth/login` | The one login, for every role |
| `GET` | `/auth/me` | Current account |
| `POST` | `/auth/me/change-password` | Change your own password |
| `POST` | `/auth/logout` | Revoke the current token |

### Scheduling (authenticated)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/schedule?week=YYYY-MM-DD` | One week of the board |
| `GET` | `/tenants/active` | Tenants selectable when scheduling |
| `POST` | `/bookings` | Create a change with mandatory documents (`multipart/form-data`; emergency requires ADMIN) |
| `GET` | `/bookings/{id}` | Owner or admin only |
| `PUT` | `/bookings/{id}` | Edit |
| `DELETE` | `/bookings/{id}` | Cancel: releases the slot, keeps the record, records who cancelled it and when |
| `GET` | `/bookings/{id}/reschedule-options` | Next available slots this caller may move the booking to |
| `POST` | `/bookings/{id}/reschedule` | Move the booking to another date/slot in one transaction |
| `GET` | `/bookings/{id}/attachments` | Document metadata |
| `POST` | `/bookings/{id}/attachments` | Upload one document |
| `DELETE` | `/bookings/{id}/attachments/{attachment_id}` | Remove a document |
| `GET` | `/bookings/{id}/attachments/{attachment_id}/download` | Download |

### Administration (role = ADMIN)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/admin/me` | Confirm administrator access |
| `GET` | `/admin/users` | List / search people |
| `PATCH` | `/admin/users/{id}/role` | Promote or demote (owner only) |
| `PATCH` | `/admin/users/{id}/status` | Activate or deactivate (an ADMIN target is owner-only) |
| `POST` | `/admin/users/{id}/reset-password` | Set a new password (an ADMIN target is owner-only) |
| `GET` `POST` | `/admin/tenants` | Tenant master |
| `PUT` `PATCH` | `/admin/tenants/{id}`, `/admin/tenants/{id}/status` | Edit / activate |
| `GET` `PUT` | `/admin/settings` | Slots per day, weekly limit, file size, mandatory documents |
| `GET` `PUT` | `/admin/slots` | Normal slot grid |
| `GET` `POST` `PUT` `DELETE` | `/admin/holidays` | Holiday management |
| `GET` | `/admin/day-capacity/{day}` | Normal slot capacity for one date |
| `POST` | `/admin/day-capacity/{day}/add-slot` | Add a normal slot to one date |
| `POST` | `/admin/day-capacity/{day}/remove-slot` | Remove a normal slot from one date |
| `DELETE` | `/admin/day-capacity/{day}` | Reset the date to the default slot count |
| `GET` | `/admin/bookings` | All changes, optionally including cancelled |
| `POST` | `/admin/bookings/emergency` | Emergency change |
| `POST` | `/admin/bookings/{id}/assign-users` | Assign one or more active RM users |
| `POST` | `/admin/bookings/{id}/move` | Move to another date/slot (emergency changes) |
| `POST` | `/admin/bookings/{id}/reassign` | Change tenant / requester / verifier |
| `POST` | `/admin/bookings/{id}/status` | Set BOOKED, COMPLETED or CANCELLED |
| `DELETE` | `/admin/bookings/{id}` | Development cleanup only; exact booking-reference confirmation required; audit retained |
| `GET` | `/admin/audit` | Audit history |

Assigned RM users use `POST /bookings/{id}/start-work` with a required `change_number`. Jira No. remains unchanged and separate.

---

## 15. Defaults at a glance

| Setting | Default |
| --- | --- |
| Slot 1 | 9:00 PM - 5:00 AM |
| Slot 2 | 9:00 PM - 5:00 AM |
| Slot 3 | 9:00 PM - 5:00 AM |
| Slot 4 | 9:00 PM - 5:00 AM |
| Emergency changes | unlimited per date, administrators only |
| Weekly limit per tenant | 2 normal changes |
| Freeze | Next 2 valid deployment dates (date-only) |
| Max upload | 20 MB per file |
| Booking reference | `PDS-YYYYMMDD-NNN` |
| Timezone | Asia/Kolkata (timestamps stored in UTC) |
| Session | 8 hours |
| POC administrator | `admin` / `admin2024` |
