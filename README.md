# Production Deployment Scheduler

A web replacement for the weekly production deployment scheduling spreadsheet.
Application/tenant teams reserve production deployment slots from a single
page; only administrators sign in.

---

## 1. Application overview

* One main page: a **Monday–Friday weekly deployment board**.
* Each working day has **four regular slots** plus a **fifth emergency slot**
  that only administrators can book.
* **Tenant users need no account.** They open the URL, see the week, book a
  free slot, and protect their booking with a **6-digit PIN**.
* Editing, cancelling and document upload require the **requester email + PIN**
  (verified on the server), and stop **48 hours** before the deployment
  (configurable).
* Administrators log in, and can configure slots, holidays, per-day overrides,
  the weekly limit and the mandatory document list; they can also override any
  rule, with the reason recorded in the audit trail.
* Every booking tracks JIRA change/task, technology, tenant, requester,
  verifier, Git repository, implementation detail and **six document
  categories** with a readiness indicator.

### Business rules (all enforced server-side)

| Rule | Default | Where it is configurable |
| --- | --- | --- |
| Regular slots per day | 4 | Admin → General, Slots, Daily override |
| Emergency slot | Slot 5, admin only | Admin → General, Slots, Daily override |
| Regular bookings per tenant per calendar week | 2 | Admin → General |
| Edit/cancel freeze before deployment | 48 hours | Admin → General |
| Maximum upload size | 20 MB per file | Admin → General |
| Mandatory documents | Test result, inventory, implementation plan, validation plan | Admin → Documents |
| Working week | Monday–Friday | fixed |
| Timezone | Asia/Kolkata | `TIMEZONE` |

Emergency bookings never count against a tenant's weekly limit. A full-day
holiday closes every regular slot; the emergency slot can optionally stay open.

---

## 2. Architecture

A **single monolithic application**: one process, one port, one origin. The
FastAPI app owns the database, the business rules, the REST API, the uploaded
files *and* the compiled React frontend. There is no reverse proxy, no API
gateway, no second web server and no service boundary to keep in sync.

```
                       ┌──────────────────────────────────────┐
   browser  ──────────▶│  python -m app      (port 8000)      │
                       │                                      │
   GET  /              │  web.py     → frontend/dist (SPA)    │
   GET  /booking/...   │  web.py     → index.html (SPA route) │
   GET  /assets/...    │  web.py     → hashed, immutable      │
   POST /api/bookings  │  api/       → services/ → SQLAlchemy │
   GET  /api/.../file  │  api/       → storage/deployments/   │
                       │                                      │
                       │  storage/scheduler.db  (SQLite)      │
                       └──────────────────────────────────────┘
```

The frontend is a separate *build*, not a separate *deployment*: Vite compiles
it to `frontend/dist`, and the same Python process serves that directory.
Because the SPA is delivered from the origin it then calls, the browser never
makes a cross-origin request and CORS is not involved at all.

```
production-deployment-scheduler/
├── backend/                     the application
│   ├── app/
│   │   ├── __main__.py          `python -m app` — starts the whole thing
│   │   ├── main.py              app assembly, middleware, router + SPA mount
│   │   ├── web.py               serves the compiled SPA and its assets
│   │   ├── config.py            env-driven settings
│   │   ├── database.py          SQLAlchemy engine/session (SQLite → Postgres)
│   │   ├── models/              AdminUser, DeploymentBooking, BookingAttachment,
│   │   │                        Holiday, DailySlotOverride, DeploymentSlotConfiguration,
│   │   │                        ApplicationSetting, BookingAudit
│   │   ├── schemas/             Pydantic request/response models
│   │   ├── api/                 schedule, bookings, attachments, admin routers
│   │   ├── services/            business rules (the source of truth)
│   │   ├── security/            hashing, JWT, auth deps, rate limiting
│   │   ├── utils/               date/timezone helpers, safe file storage
│   │   └── seed.py              development sample data
│   ├── tests/                   100 backend tests
│   └── requirements.txt
├── frontend/                    React + TypeScript + Vite + Tailwind CSS v4
│   ├── dist/                    build output, served by the Python process
│   └── src/
│       ├── components/          AppHeader, WeekNavigator, ScheduleSummary,
│       │                        WeeklySchedule, DaySchedule, DeploymentSlot,
│       │                        BookingDrawer, BookingForm, BookingDetailsDrawer,
│       │                        DocumentUploader, DocumentReadiness,
│       │                        OwnerVerificationModal, MyBookingsModal,
│       │                        AdminLoginModal, AdminPanel, AuditHistory,
│       │                        ToastNotification, Modal, Drawer, Icons
│       ├── hooks/               useSchedule, useAdminSession
│       ├── services/api.ts      REST client
│       ├── types/               API types
│       └── utils/               date + formatting helpers
├── storage/                     runtime data (git-ignored)
│   ├── scheduler.db             SQLite database
│   └── deployments/<booking-id>/<category>/
├── .env.example
└── README.md
```

**Architectural rule:** the backend is the source of truth. Slot availability,
the weekly limit, ownership, the emergency-slot restriction, freeze
calculations and holiday handling are all revalidated in the API on every
write. The frontend's copies exist only for immediate feedback.

Communication is plain REST/JSON over relative `/api` paths. Request routing
inside the process:

| Request | Handled by |
| --- | --- |
| `/api/...` | the API routers; an unknown path returns a JSON 404 |
| `/docs`, `/redoc`, `/openapi.json` | FastAPI's own docs |
| an existing file under `frontend/dist` | served directly (hashed assets get a one-year immutable cache; `index.html` is never cached) |
| anything else | `index.html`, so React handles the client-side route |

The SPA catch-all is registered last, so a real endpoint always wins. Static
paths are resolved and then re-checked against the build directory, so a
crafted URL cannot read a file outside it.

---

## 3. Prerequisites

* Python 3.11+ (developed on 3.14)
* Node.js 20+ (developed on 24)
* No database server required — SQLite is the default.

---

## 4. Configuration

```bash
cp .env.example .env
```

Then edit `.env`:

```ini
ENVIRONMENT=development
DATABASE_URL=sqlite:///./storage/scheduler.db
STORAGE_DIR=./storage/deployments
JWT_SECRET=<long random string>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<strong password>
FRONTEND_DIST=./frontend/dist
CORS_ORIGINS=
TIMEZONE=Asia/Kolkata
```

Leave `CORS_ORIGINS` empty. The UI is served from the same origin as the API,
so nothing is cross-origin; set it only if you deliberately host the UI
elsewhere.

Generate a secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`ADMIN_USERNAME` / `ADMIN_PASSWORD` seed **one** administrator on first start.
The password is hashed with bcrypt immediately and never stored in clear text.
If that username already exists the row is left untouched, so changing the env
var later will not silently reset a chosen password. With
`ENVIRONMENT=production` the app refuses to start while `JWT_SECRET` or
`ADMIN_PASSWORD` are still at their placeholder values.

---

## 5. Install and run

Three commands to install, one to run.

### 1. Install the application

```bash
cd backend && python -m venv .venv
```

```bash
cd backend && .venv/Scripts/python -m pip install -r requirements.txt
```

(macOS/Linux: `.venv/bin/python` instead of `.venv/Scripts/python` throughout.)

### 2. Build the frontend

```bash
cd frontend && npm install && npm run build
```

This writes `frontend/dist`, which the application serves. Repeat it whenever
you change frontend code (or use the dev server in §6 while working on it).

### 3. Start the application

```bash
cd backend && .venv/Scripts/python -m app
```

That is the whole system: **<http://127.0.0.1:8000>** serves the scheduler UI,
the REST API and the uploaded documents. Interactive API docs are at
<http://127.0.0.1:8000/docs>.

Options:

```bash
cd backend && .venv/Scripts/python -m app --host 0.0.0.0 --port 8000 --workers 4
```

```bash
cd backend && .venv/Scripts/python -m app --reload
```

`python -m app` is a thin wrapper around uvicorn, so the explicit form works
too:

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000
```

If the frontend has not been built, the API still starts and the web root
shows the build instructions instead of the board.

### Database initialisation

The schema, the default slot grid (4 regular + 1 emergency) and the seed
administrator are created automatically on first start — no migration step is
required. To do it explicitly:

```bash
cd backend && .venv/Scripts/python -c "from app.services import bootstrap; bootstrap.initialise()"
```

### Sample data (development only)

```bash
cd backend && .venv/Scripts/python -m app.seed
```

This adds the 14 Sep 2026 *Indian Public Holiday*, two bookings on 15 Sep 2026
(Encounters / CHG0920798 / Databricks and EPCAT / CHG0920763 / AzDF) and one
booking next week. **Every sample booking uses PIN `123456`.**

---

## 6. Frontend development (optional)

For hot-reloading while editing React code, run Vite alongside the application
and work on <http://localhost:5173> instead. Vite proxies `/api` to port 8000,
so the browser still only talks to one origin and no CORS configuration is
needed.

```bash
cd frontend && npm run dev
```

This is a development convenience only — nothing is deployed this way. When
you are finished, `npm run build` and go back to port 8000.

```bash
cd frontend && npm run typecheck
```

---

## 7. Deployment

The deployable unit is the repository plus a built frontend. There is nothing
to orchestrate.

```bash
cd frontend && npm ci && npm run build
```

```bash
cd backend && .venv/Scripts/python -m app --host 0.0.0.0 --port 8000 --workers 4
```

Put TLS in front of it (nginx, Caddy, a load balancer) if it is internet
facing. A proxy is optional and only terminates TLS — it does not need to route
`/api` separately:

```nginx
location / { proxy_pass http://127.0.0.1:8000; }
```

A systemd unit is enough to run it as a service:

```ini
[Service]
WorkingDirectory=/srv/pds/backend
EnvironmentFile=/srv/pds/.env
ExecStart=/srv/pds/backend/.venv/bin/python -m app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
```

With SQLite, keep `--workers 1` for write-heavy use or move to PostgreSQL (§11)
before scaling out; multiple workers also mean the login rate limiter and the
logout revocation list are per-worker.

---

## 8. Testing

```bash
cd backend && .venv/Scripts/python -m pytest
```

100 tests cover the rules that matter:

* booking succeeds without login; reference numbers are sequential and unique
* a slot cannot be double-booked — including **eight concurrent threads racing
  for one slot**, where exactly one wins and the rest get a 409
* the emergency slot is refused to the public and accepted for an admin
* emergency bookings require a reason and a justification
* the weekly tenant limit blocks the third booking, is case-insensitive, resets
  next week, and can be overridden by an admin *with a recorded reason*
* ownership: right PIN edits, wrong PIN and another user's email are refused
* the freeze window blocks public edit/cancel and allows admin edits
* holidays block regular slots, can keep or close the emergency slot, and
  partial holidays stay open
* daily overrides reduce slots and disable the emergency slot for one date
* document readiness, mandatory-document configuration, file-type/size limits,
  filename sanitisation and path-traversal safety
* attachment download requires an admin session or the booking's own token
* admin authentication, rate limiting, logout revocation, and the audit trail
* the monolith's serving layer: the API and UI answer on one origin with no
  CORS headers, an unknown `/api` path returns JSON rather than HTML, `/docs`
  is not swallowed by the SPA catch-all, client-side routes such as
  `/booking/manage/<token>` fall back to the shell, hashed assets are cached
  immutably while `index.html` is not, and traversal attempts like
  `/assets/../../.env` cannot read outside the build directory

### Frontend scenarios verified manually in the browser

Against the single process on port 8000: previous/next week and Today, the
booking drawer and success screen, emergency booking as admin, booking details,
ownership verification (masked contacts becoming visible), admin login/logout,
the seven admin-control sections, holiday display, emergency-slot lock for the
public, and the stacked mobile layout at 375 px with no horizontal scrolling.

---

## 9. File storage

Attachments live outside the database:

```
storage/deployments/<booking-id>/
    test-results/        inventory/           implementation-plan/
    validation-plan/     dba-script/          supporting-documents/
```

Stored filenames are freshly generated UUIDs plus a whitelisted extension; the
name the user uploaded is kept only as a display label. Files are never
executed, never served inline, and every resolved path is re-checked against
the storage root.

Allowed types: `.pdf .doc .docx .xls .xlsx .csv .txt .zip .sql .png .jpg .jpeg`

---

## 10. Backup procedure

Two things need backing up — the database and the uploaded documents. Both are
under `storage/`.

```bash
sqlite3 storage/scheduler.db ".backup 'backup/scheduler-$(date +%F).db'"
```

```bash
tar -czf backup/deployments-$(date +%F).tar.gz storage/deployments
```

Take both in the same window so references and files stay consistent. Restore
by stopping the app, replacing `storage/`, and starting it again. On PostgreSQL
use `pg_dump` for the database and keep the same archive step for `storage/`.

---

## 11. Moving to PostgreSQL

```ini
DATABASE_URL=postgresql+psycopg://scheduler:secret@localhost:5432/scheduler
```

Install the driver (`pip install "psycopg[binary]"`) and restart. No code
changes are needed: the only SQLite-specific code is the connection pragma
block in `app/database.py`, and the partial unique index that prevents double
booking is declared for both dialects.

---

## 12. Security notes

* **Passwords and PINs are hashed** with bcrypt (cost 12) over a SHA-256
  pre-hash, so nothing is truncated at bcrypt's 72-byte limit. Neither is ever
  stored, logged, returned by an API, or written to the audit trail.
* **Admin sessions** are HS256 JWTs carried in `Authorization: Bearer`. No
  cookies are issued, so there is no CSRF surface. Logout revokes the token id
  server-side in addition to the client discarding it.
* **Ownership is verified in the backend** on every edit, cancel, upload and
  attachment delete. Credentials travel in the request body — a booking PIN is
  never placed in a URL, query string or browser history.
* **Attachment downloads** require an admin session or the booking's opaque
  management token (rotated on each successful PIN verification). They are sent
  as `application/octet-stream` with `nosniff` and a `Content-Disposition`
  attachment header.
* **Rate limiting** protects the three endpoints that accept secrets: admin
  login (8 per 5 min per IP), PIN verification and *Find my bookings* (10 per
  5 min per IP).
* **Anonymous visitors see a redacted booking**: tenant, JIRA, verifier,
  technology, status and document readiness are public, but requester and
  verifier email addresses and phone numbers are masked until the owner
  verifies or an admin signs in.
* **Failed logins return one message** for an unknown user and a wrong
  password, so the endpoint cannot be used to enumerate accounts.
* **Concurrency** is handled by a partial unique index on
  `(deployment_date, slot_number)` for non-cancelled rows, not by a
  check-then-insert, so a race can only ever produce one winner.
* **Same-origin by construction.** Serving the UI from the application removes
  CORS from the picture entirely: `CORS_ORIGINS` is empty by default and the
  middleware is not even installed unless you set it.
* **Static serving is confined to the build directory.** Every requested path
  is resolved and re-checked against `frontend/dist`, so `/../.env` or
  `/assets/../../.env` cannot read application files. Only existing files are
  served; everything else returns the SPA shell.
* Unhandled exceptions return a generic message; stack traces and SQL are
  logged server-side only.
* Responses carry `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`
  and `Referrer-Policy: no-referrer`.

Before going live: set `ENVIRONMENT=production`, a unique `JWT_SECRET`, a strong
`ADMIN_PASSWORD`, leave `CORS_ORIGINS` empty, and terminate TLS in front of the
process.

---

## 13. API overview

All routes are under `/api` on the same origin as the UI. Interactive
documentation: `/docs`.

### Public

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/schedule?week=YYYY-MM-DD` | One week of the board (any date inside it) |
| `GET` | `/config` | Public settings: limits, technologies, document catalogue |
| `POST` | `/bookings` | Create a booking (emergency slot requires admin) |
| `GET` | `/bookings/{id}` | Booking detail; contacts redacted for anonymous callers |
| `POST` | `/bookings/{id}/verify-owner` | Email + PIN → full detail and a manage token |
| `GET` | `/bookings/manage/token/{token}` | Open a booking from its management link |
| `PUT` | `/bookings/{id}` | Edit (owner credentials, or admin bearer) |
| `DELETE` | `/bookings/{id}` | Cancel and release the slot |
| `POST` | `/bookings/{id}/attachments` | Upload one document (multipart) |
| `GET` | `/bookings/{id}/attachments` | Attachment metadata |
| `DELETE` | `/bookings/{id}/attachments/{attachment_id}` | Remove a document |
| `GET` | `/bookings/{id}/attachments/{attachment_id}/download` | Download (admin or manage token) |
| `POST` | `/my-bookings` | Find all bookings for an email + PIN |
| `GET` | `/health` | Liveness |

### Admin (requires `Authorization: Bearer <token>`)

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/admin/login` | Sign in |
| `POST` | `/admin/logout` | Revoke the current token |
| `GET` | `/admin/me` | Current administrator |
| `GET` `PUT` | `/admin/settings` | Slots per day, weekly limit, freeze hours, file size, mandatory documents |
| `GET` `PUT` | `/admin/slots` | Slot names, times, regular/emergency, enabled |
| `GET` `POST` | `/admin/holidays` | List / create |
| `PUT` `DELETE` | `/admin/holidays/{id}` | Update / delete |
| `GET` `PUT` | `/admin/overrides` | Per-date slot overrides |
| `DELETE` | `/admin/overrides/{id}` | Clear an override |
| `GET` | `/admin/bookings` | All bookings, optionally including cancelled |
| `POST` | `/admin/bookings/emergency` | Emergency booking |
| `POST` | `/admin/bookings/{id}/move` | Move to another date/slot |
| `POST` | `/admin/bookings/{id}/reassign` | Change tenant / requester / verifier |
| `POST` | `/admin/bookings/{id}/status` | Set BOOKED, COMPLETED or CANCELLED |
| `DELETE` | `/admin/bookings/{id}` | Permanently delete a booking and its files |
| `GET` | `/admin/audit` | Audit history, optionally per booking |

---

## 14. Using the app

**As a tenant user**

1. Open the scheduler URL (`http://<server>:8000/`) and use
   **Previous week / Next week / Today**.
2. Click **Book slot** on a green slot; the drawer opens over the board.
3. Fill the change, people and deployment sections, choose a 6-digit PIN, and
   confirm. The booking reference (`PDS-20260921-003`) appears immediately,
   followed by the document uploader.
4. Attach the four required documents. Readiness shows as `3 / 4 required`.
5. To change anything later, click the booking → **Verify ownership** → enter
   your email and PIN. Inside the 48-hour window the drawer shows
   **Booking locked** instead of the action buttons.
6. Forgot which slots are yours? **Find my bookings** → email + PIN.

**As an administrator**

1. **Admin login** (top right) → **Admin controls**.
2. *General* — slots per day, weekly limit, freeze hours, file size.
   *Slots* — names, times, emergency flag, enabled.
   *Holidays* — add/edit/delete, full or partial day, emergency allowed.
   *Daily override* — a different grid for one date.
   *Documents* — which categories are mandatory.
   *Bookings* — open, complete or permanently delete.
   *Audit* — every create, edit, move, cancel, document change and override.
3. Book slot 5 with **Book emergency change**; the form adds emergency reason,
   approver, approval reference and business justification.
4. Overriding the weekly limit or the freeze window asks for a reason, which is
   stored in the audit trail.

---

## 15. Defaults at a glance

| Setting | Default |
| --- | --- |
| Slot 1 | 07:00 – 09:00 |
| Slot 2 | 09:00 – 11:00 |
| Slot 3 | 11:00 – 13:00 |
| Slot 4 | 14:00 – 16:00 |
| Emergency slot 5 | 16:00 – 18:00 (admin only) |
| Weekly limit per tenant | 2 regular bookings |
| Freeze window | 48 hours |
| Max upload | 20 MB per file |
| Booking reference | `PDS-YYYYMMDD-NNN` |
| Timezone | Asia/Kolkata (timestamps stored in UTC) |
| Admin session | 8 hours |
