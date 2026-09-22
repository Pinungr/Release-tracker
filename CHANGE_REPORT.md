# Scheduling fixes and verification

Implemented in the existing application on 22 September 2026. No schema or
migration changes were introduced. Existing user changes to the entity model,
migration files and configuration were preserved.

## Files changed

| Area | Files | Changes |
| --- | --- | --- |
| Normal scheduling | `backend/app/services/booking_service.py`, `backend/app/services/schedule_service.py` | Shared normal slot validation, strict rescheduling, explicit manual overrides, date protection, capacity independent of disabled rows. |
| Response permissions | `backend/app/services/presenters.py`, `backend/app/schemas/booking.py` | Lock reasons, caller-specific modification/download permissions, accurate availability and separate configured capacity. |
| API enforcement | `backend/app/api/bookings.py`, `backend/app/api/attachments.py`, `backend/app/api/admin.py`, `backend/app/schemas/admin.py` | Caller identity in responses; protected attachments, assignment, work and status; explicit move overrides; guarded development cleanup. |
| Authentication config | `backend/app/config.py` | Reject known JWT placeholders and secrets shorter than 32 characters in production. |
| Booking UI | `frontend/src/components/BookingDetailsDrawer.tsx`, `frontend/src/components/DocumentUploader.tsx`, `frontend/src/types/index.ts` | Backend permission flags, correct lock messages, assigned-RM download controls, optional Jira guidance; emergency move form separate from the normal picker. |
| Admin/board UI | `frontend/src/components/AdminPanel.tsx`, `frontend/src/components/DaySchedule.tsx`, `frontend/src/components/DeploymentSlot.tsx` | Cancellation replaces normal destructive removal; locked actions hidden; corrected date/availability wording. |
| Docker/environment | `docker-compose.yml`, `.env.example`, `.gitignore`, root `.env` tracking | Configurable `POSTGRES_IMAGE`; accurate Compose/local environment comments. Root `.env` removed from Git tracking and ignored; its local contents were preserved. |
| Documentation | `README.md`, `CHANGE_REPORT.md` | Implemented business rules, overnight timing, optional Jira, environment precedence, localhost PostgreSQL exposure, exceptional overrides, audit retention and test commands. |
| New backend checks | `backend/tests/test_normal_availability.py`, `backend/tests/test_production_config.py`, `backend/tests/docker_smoke.py` | Invalid availability/API targets, date locks, permissions, missing slots, JWT validation and disposable PostgreSQL integration. |
| Existing backend tests | `backend/tests/conftest.py`, `backend/tests/test_admin_management.py`, `backend/tests/test_emergency_and_holidays.py`, `backend/tests/test_monolith_serving.py`, `backend/tests/test_rm_assignment_and_audit.py`, `backend/tests/test_weekly_limit_and_freeze.py` | Preserve regressions while requiring explicit overrides/deletion confirmation; update stale migration comment and HTML cache assertion to the existing no-store behavior. |
| Frontend checks | `frontend/src/components/BookingPermissions.test.tsx`, `frontend/vitest.config.ts`, `frontend/package.json`, `frontend/package-lock.json` | Seven component tests and an `npm test` command, with test dependencies compatible with the Docker Node runtime. |

## Business rules implemented

1. Normal board availability, counters and reschedule options use shared
   validation for both Admin and normal users. Friday/Saturday, full-day
   holidays, past/current/protected dates, manually frozen slots, disabled
   slots, slots above date capacity, missing slots and occupied slots are
   excluded. Options are ordered by date, then slot number.
2. Direct reschedule POSTs enforce the same destination rules. Invalid moves
   leave the original booking and audit history unchanged. Tenant quotas apply
   to normal users; the existing audited Admin weekly-limit exception remains.
3. Exceptional Admin booking/move API operations require `manual_override: true`
   and a nonempty `override_reason` to bypass normal weekend/holiday/manual
   freeze/disabled-capacity restrictions. Reschedule POST never uses this
   override. Missing/occupied slots and past/current/protected dates cannot be
   overridden.
4. Date protection also applies to emergency records, assignment, RM work,
   Change Number changes, status changes and attachment mutations. Responses
   expose `can_edit`, `can_cancel`, `can_reschedule`, `can_assign_rm`,
   `can_start_work`, `can_manage_attachments` and `can_download_attachments`.
5. Lock reasons distinguish current date, past date, automatic date freeze and
   manual slot freeze. The drawer explains the actual reason and hides
   unavailable modification controls, including for Admin.
6. Assigned RM users can download authorized documents, including from locked
   records, without receiving upload/delete or booking ownership permissions.
   Reassignment removes their access.
7. Counters distinguish configured capacity from currently available slots.
   The displayed total includes booked slots plus free bookable slots; closed
   empty slots never inflate availability. Capacity adjustment uses the
   configured date limit rather than the count of enabled rows.
8. Normal Admin removal cancels the booking, preserving documents and history.
   Permanent deletion is an exceptional development-only API requiring exact
   booking-reference confirmation. It deletes booking/files but retains audit
   events and the deletion snapshot; production rejects it.
9. Production rejects both JWT placeholders and secrets shorter than 32
   characters. Development placeholders remain supported. Docker uses root
   environment configuration; local Python also reads `backend/.env`, with
   process variables taking precedence. PostgreSQL remains bound to host
   localhost at port 15432, and its image is configurable.

## Intentionally retained

The existing design, database schema/migration chain, tenant weekly limits,
audited Admin weekly-limit exception, per-date capacity, emergency queue,
cancellation/reschedule identity and audit retention, RM assignment, separate
Change Number workflow, document requirements, authentication and
password-change token invalidation remain. Jira is optional by default and
configurably required. Default slot timing remains 9 PM to 5 AM the next day.
Explicit Admin edits/cancellations of manually frozen future records remain
available outside automatic date protection.

The five-day board still shows Sunday through Thursday. Exceptional weekend
records remain accessible through Admin booking management. The existing
requirement to select at least one RM when saving assignment is retained.

## Verification results

| Check | Result |
| --- | --- |
| Complete backend suite, with `FRONTEND_DIST` set to the built SPA | **244 passed, 0 skipped** |
| Freeze/reschedule tests after final unreachable-audit-text cleanup | **47 passed** |
| Frontend component tests (`npm test`) | **7 passed** |
| TypeScript and production frontend build (`npm run build`) | **Passed** |
| Docker image build | **Passed** |
| `docker compose config --quiet` | **Passed** |
| Disposable production-mode Docker/PostgreSQL integration | **Passed**: readiness, SPA, authentication, booking, optional Jira, overnight timing, availability, invalid destinations, rescheduling, cancellation and audit retention |
| `git diff --check` | **Passed** |

The disposable containers/network were removed. Existing running application
containers and data were not changed. The full backend suite uses isolated
SQLite databases; the separate Docker smoke check exercises PostgreSQL.

All requested acceptance scenarios pass: Admin rescheduling excludes Saturday
and Friday; next availability skips holidays and protected dates; current-date
records are read-only; Jira remains optional; slots retain 9 PM-5 AM timing;
assigned RM downloads are authorized; README rules match the implementation.

No remaining functional issue was found in the requested scope. Existing
Starlette/httpx and HTTP status-alias deprecation warnings remain. No commit
or deployment to the existing running application was performed.
