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
│   │   │                        DailySlotOverride, ApplicationSetting, BookingAudit
│   │   ├── schemas/             Pydantic request/response models
│   │   ├── api/                 auth, schedule, bookings, attachments, tenants, admin
│   │   ├── services/            business rules (the source of truth)
│   │   ├── security/            hashing, JWT, auth dependencies, rate limiting
│   │   ├── utils/               date/timezone helpers, safe file storage
│   │   └── seed.py              demo data
│   ├── tests/                   149 backend tests
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
ownership, the tenant weekly limit, the freeze window, holiday blocking and
emergency-change access are all revalidated in the API on every write. The
frontend's copies exist only for immediate feedback.

---

## 2. Roles and access

| | TENANT_USER | ADMIN |
| --- | --- | --- |
| Sign up | self-service | promoted by an admin |
| See the weekly board | ✅ | ✅ |
| Schedule a normal change | ✅ | ✅ |
| See / edit / cancel a change | only their own | any |
| Upload and download documents | only on their own changes | any |
| Emergency changes | view only | create, edit, cancel |
| Exceed the tenant weekly limit | ❌ | ✅ with an audited reason |
| Edit inside the freeze window | ❌ | ✅ with an audited reason |
| Users, tenants, holidays, slots, settings, audit | ❌ | ✅ |

Everyone uses **one login**. There is no separate administrator sign-in and no
separate administrator table — `users.role` is the only thing that grants
administrator access, and it is re-read from the database on every request, so
promoting, demoting or deactivating an account takes effect immediately.

---

## 3. Business rules

| Rule | Default | Configurable in |
| --- | --- | --- |
| Normal deployment slots per day | 4 | Admin → General / Slots / Daily override |
| Emergency changes | unlimited per date, admin only | Admin → General / Daily override |
| Normal changes per **tenant** per week | 2 | Admin → General |
| Edit/cancel freeze before deployment | **48 hours** | Admin → General |
| Maximum upload size | 20 MB per file | Admin → General |
| Mandatory documents | Test result, inventory, implementation plan, validation plan | Admin → Documents |
| Working week | Monday–Friday | fixed |
| Timezone | Asia/Kolkata | `TIMEZONE` |

**The weekly limit is per tenant, not per user.** If user A and user B each
schedule one change for Tenant X in the same week, Tenant X is at 2/2 and
nobody may add a third — but both users still have the full quota available
for any other tenant.

**Emergency changes are a queue, not a slot.** Any number can sit on the same
date, they carry no slot number, they never consume normal deployment capacity,
and they never count against a tenant's weekly quota.

```
DAY
├── Normal Slot 1   07:00 – 09:00
├── Normal Slot 2   09:00 – 11:00
├── Normal Slot 3   11:00 – 13:00
├── Normal Slot 4   14:00 – 16:00
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

PostgreSQL runs on the internal Compose network as `postgres:5432` and is
**not** published to the host. The application reaches it over that network
only.

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
   this is per change record, not per account.
4. Attach the required documents; readiness shows as `3 / 4 required`.
5. Your own changes are badged **My booking**; the **My changes** card filters
   the board to them.
6. Edit or cancel your own change up to **48 hours** before deployment. Inside
   that window the drawer shows **Booking locked** instead of the buttons.
7. **Profile** shows your account and lets you change your password.

**As an administrator**

1. Sign in with the same form; the header gains **Admin controls**.
2. *Users* — promote/demote, activate/deactivate, reset a password. You never
   see an existing password or hash. The last active administrator cannot be
   demoted or deactivated.
3. *Tenants* — add, edit, activate, deactivate. Only active tenants appear in
   the scheduling form.
4. *General* — slots per day, weekly limit, freeze hours, upload size.
   *Slots* — names and times of the normal slots.
   *Holidays* — full or partial day, emergency allowed or not.
   *Daily override* — a different grid for one date.
   *Documents* — which categories are mandatory.
   *Bookings* — open, complete or permanently delete.
   *Audit* — every create, edit, move, cancel, document change and override.
5. **Add emergency CR** on any day's emergency queue. The form additionally
   requires an emergency reason and business justification.
6. Overriding the weekly limit or the freeze window asks for a reason, which is
   stored in the audit trail.

---

## 9. Documents

Six categories, four mandatory by default:

| Category | Default | Files |
| --- | --- | --- |
| Non-Production Test Result | required | one |
| Inventory File | required | one |
| Implementation Plan | required | one |
| Validation Plan | required | one |
| DBA Script | optional | one |
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
`holidays`, `slot_configurations`, `daily_slot_overrides`,
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

**149 tests, all passing.** They cover the rules that matter:

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
* the 48-hour freeze blocks the owner's edit, cancel and upload; an admin may
  override with a reason
* multiple emergency changes on one date, admin-only, consuming neither slots
  nor quota; tenant users are refused
* holidays block normal slots and can keep or close the emergency queue;
  partial holidays stay open; daily overrides resize one date
* document readiness, configurable mandatory set, file-type and size limits,
  filename sanitisation, and owner/admin-only download
* concurrency: eight simultaneous requests for one slot leave exactly one
  winner; five simultaneous emergency changes on one date all succeed
* the monolith's serving layer, including traversal attempts under `/assets`
* configuration safety: production refuses to start on any credential this
  repository ships, and relative paths resolve against the project root

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

## 13. Security notes

* **Passwords are hashed** with bcrypt (cost 12) over a SHA-256 pre-hash, so
  nothing is truncated at bcrypt's 72-byte limit. A password is never stored,
  logged, returned by an API, or written to the audit trail — administrators
  can set a new one but can never see an existing one.
* **Sessions** are HS256 JWTs in `Authorization: Bearer`. The token carries
  identity only; the **role is read from the database on every request**, so
  there is exactly one source of truth for authorization. No cookies are
  issued, so there is no CSRF surface. Logout revokes the token id server-side.
* **Ownership** is `created_by_user_id` versus the authenticated caller,
  checked in the API for every read, edit, cancel, upload, download and delete.
* **Authentication is checked before authorization**, so an anonymous caller
  always gets 401 and never a misleading 403.
* **Rate limiting** protects sign-up, login and password change.
* **Concurrency** is handled by a partial unique index on
  `(deployment_date, slot_number)` for non-cancelled, non-emergency rows — not
  by a check-then-insert — so a race can only ever produce one winner.
* **Self-lockout protection**: the last active administrator cannot be demoted
  or deactivated.
* PostgreSQL is not published to the host; the app talks to it over the
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
| `POST` | `/admin/logout` | Revoke the current token |

### Scheduling (authenticated)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/schedule?week=YYYY-MM-DD` | One week of the board |
| `GET` | `/tenants/active` | Tenants selectable when scheduling |
| `POST` | `/bookings` | Create a change (emergency requires ADMIN) |
| `GET` | `/bookings/{id}` | Owner or admin only |
| `PUT` | `/bookings/{id}` | Edit |
| `DELETE` | `/bookings/{id}` | Cancel and release the slot |
| `GET` | `/bookings/{id}/attachments` | Document metadata |
| `POST` | `/bookings/{id}/attachments` | Upload one document |
| `DELETE` | `/bookings/{id}/attachments/{attachment_id}` | Remove a document |
| `GET` | `/bookings/{id}/attachments/{attachment_id}/download` | Download |

### Administration (role = ADMIN)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/admin/me` | Confirm administrator access |
| `GET` | `/admin/users` | List / search people |
| `PATCH` | `/admin/users/{id}/role` | Promote or demote |
| `PATCH` | `/admin/users/{id}/status` | Activate or deactivate |
| `POST` | `/admin/users/{id}/reset-password` | Set a new password |
| `GET` `POST` | `/admin/tenants` | Tenant master |
| `PUT` `PATCH` | `/admin/tenants/{id}`, `/admin/tenants/{id}/status` | Edit / activate |
| `GET` `PUT` | `/admin/settings` | Slots per day, weekly limit, freeze hours, file size, mandatory documents |
| `GET` `PUT` | `/admin/slots` | Normal slot grid |
| `GET` `POST` `PUT` `DELETE` | `/admin/holidays` | Holiday management |
| `GET` `PUT` `DELETE` | `/admin/overrides` | Per-date slot overrides |
| `GET` | `/admin/bookings` | All changes, optionally including cancelled |
| `POST` | `/admin/bookings/emergency` | Emergency change |
| `POST` | `/admin/bookings/{id}/move` | Move to another date/slot |
| `POST` | `/admin/bookings/{id}/reassign` | Change tenant / requester / verifier |
| `POST` | `/admin/bookings/{id}/status` | Set BOOKED, COMPLETED or CANCELLED |
| `DELETE` | `/admin/bookings/{id}` | Permanently delete a change and its files |
| `GET` | `/admin/audit` | Audit history |

---

## 15. Defaults at a glance

| Setting | Default |
| --- | --- |
| Slot 1 | 07:00 – 09:00 |
| Slot 2 | 09:00 – 11:00 |
| Slot 3 | 11:00 – 13:00 |
| Slot 4 | 14:00 – 16:00 |
| Emergency changes | unlimited per date, administrators only |
| Weekly limit per tenant | 2 normal changes |
| Freeze window | 48 hours |
| Max upload | 20 MB per file |
| Booking reference | `PDS-YYYYMMDD-NNN` |
| Timezone | Asia/Kolkata (timestamps stored in UTC) |
| Session | 8 hours |
| POC administrator | `admin` / `admin2024` |
