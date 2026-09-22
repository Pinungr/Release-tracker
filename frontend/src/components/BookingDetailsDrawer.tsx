import { useEffect, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { BookingDetail, ManagedUser, PublicSettings, SlotConfig } from '../types'
import { formatDate, formatTimestamp } from '../utils/dates'
import { DocumentReadinessPanel } from './DocumentReadiness'
import { DocumentUploader } from './DocumentUploader'
import { Drawer } from './Drawer'
import { Alert, Calendar, Clock, Link as LinkIcon, Lock, Pencil, Spinner, Trash, User } from './Icons'
import { ConfirmationModal, Modal } from './Modal'
import { RescheduleModal } from './RescheduleModal'
import { BookingStatusBadge, EmergencyBadge, LockBadge } from './StatusBadge'
import { useToast } from './ToastNotification'

interface BookingDetailsDrawerProps {
  open: boolean
  onClose: () => void
  booking: BookingDetail | null
  loading: boolean
  settings: PublicSettings
  isAdmin: boolean
  timezone: string
  userId: number | null
  onEdit: (booking: BookingDetail) => void
  onChanged: () => void
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="col-span-2 grid grid-cols-subgrid gap-x-4 border-b border-line/70 py-2 last:border-0">
      <dt className="text-xs font-semibold tracking-wide text-ink-muted uppercase">{label}</dt>
      <dd className="min-w-0 text-sm break-words text-ink">{children}</dd>
    </div>
  )
}

export function BookingDetailsDrawer({
  open,
  onClose,
  booking,
  loading,
  settings,
  isAdmin,
  timezone,
  userId,
  onEdit,
  onChanged,
}: BookingDetailsDrawerProps) {
  const toast = useToast()
  const [confirmCancel, setConfirmCancel] = useState(false)
  const [rescheduleOpen, setRescheduleOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [moveOpen, setMoveOpen] = useState(false)
  const [moveDate, setMoveDate] = useState('')
  const [moveSlot, setMoveSlot] = useState('')
  const [moveSlots, setMoveSlots] = useState<SlotConfig[]>([])
  const [moveBusy, setMoveBusy] = useState(false)
  const [moveError, setMoveError] = useState<string | null>(null)
  const [assignmentUsers, setAssignmentUsers] = useState<ManagedUser[]>([])
  const [selectedAssignees, setSelectedAssignees] = useState<number[]>([])
  const [assignmentBusy, setAssignmentBusy] = useState(false)
  const [changeNumber, setChangeNumber] = useState('')
  const [workBusy, setWorkBusy] = useState(false)
  const [workError, setWorkError] = useState<string | null>(null)

  const ownsBooking = booking !== null && userId === booking.created_by_user_id
  const historicalReadOnly = booking?.is_past ?? false

  const canAct =
    booking !== null &&
    !historicalReadOnly &&
    booking.status !== 'CANCELLED' &&
    (isAdmin || ownsBooking)
  const publicLocked = booking !== null && booking.is_locked && !isAdmin
  const isAssigned = booking !== null && userId !== null && booking.assigned_users.some((u) => u.user_id === userId)

  useEffect(() => {
    setSelectedAssignees(booking?.assigned_users.map((u) => u.user_id) ?? [])
    setChangeNumber(booking?.change_number ?? '')
    setWorkError(null)
    if (open && isAdmin && !booking?.is_past) {
      void api.listUsers().then((users) => setAssignmentUsers(users.filter((u) => u.is_active && u.role === 'TENANT_USER' && u.id !== booking?.created_by_user_id))).catch(() => setAssignmentUsers([]))
    }
  }, [booking?.id, booking?.change_number, open, isAdmin])

  async function saveAssignments() {
    if (!booking || !isAdmin || booking.is_past) return
    if (!selectedAssignees.length) {
      toast.error('Select at least one RM user.')
      return
    }
    setAssignmentBusy(true)
    try {
      await api.assignBookingUsers(booking.id, selectedAssignees)
      toast.success('RM users assigned.', booking.booking_reference)
      onChanged()
    } catch (error) {
      toast.error('Could not assign RM users', error instanceof ApiError ? error.message : 'Please try again.')
    } finally {
      setAssignmentBusy(false)
    }
  }

  async function startWork() {
    if (!booking || booking.is_past) return
    if (!changeNumber.trim()) {
      setWorkError('Change No. is required to start work.')
      return
    }
    setWorkBusy(true)
    setWorkError(null)
    try {
      await api.startWork(booking.id, changeNumber.trim())
      toast.success(booking.change_number ? 'Change No. updated.' : 'Work started.', changeNumber.trim())
      onChanged()
    } catch (error) {
      setWorkError(error instanceof ApiError ? error.message : 'Could not start work.')
    } finally {
      setWorkBusy(false)
    }
  }

  async function cancel() {
    if (!booking) return
    setBusy(true)
    try {
      await api.cancelBooking(booking.id, { override_reason: null })
      toast.success('Booking cancelled.', `${booking.booking_reference} · the slot is now free.`)
      setConfirmCancel(false)
      onChanged()
      onClose()
    } catch (error) {
      const message = error instanceof ApiError ? error.message : 'Please try again.'
      if (error instanceof ApiError && error.status === 423) toast.locked('This booking is locked', message)
      else toast.error('Could not cancel the booking', message)
    } finally {
      setBusy(false)
    }
  }

  async function openMoveDialog() {
    if (!booking || !isAdmin || booking.is_past) return
    setMoveDate(booking.deployment_date)
    setMoveSlot(booking.slot_number ? String(booking.slot_number) : '')
    setMoveError(null)
    setMoveOpen(true)
    if (!booking.is_emergency) {
      try {
        setMoveSlots(await api.getSlots())
      } catch (error) {
        setMoveError(error instanceof ApiError ? error.message : 'Could not load deployment slots.')
      }
    }
  }

  async function moveBooking() {
    if (!booking) return
    if (!moveDate) {
      setMoveError('Select the new deployment date.')
      return
    }
    if (!booking.is_emergency && !moveSlot) {
      setMoveError('Select the new deployment slot.')
      return
    }
    setMoveBusy(true)
    setMoveError(null)
    try {
      await api.moveBooking(booking.id, {
        deployment_date: moveDate,
        slot_number: booking.is_emergency ? null : Number(moveSlot),
        override_reason: null,
      })
      toast.success(
        booking.is_emergency ? 'Emergency CRQ moved.' : 'Deployment rescheduled.',
        `${booking.booking_reference} · ${formatDate(moveDate)}`,
      )
      setMoveOpen(false)
      onChanged()
    } catch (error) {
      setMoveError(error instanceof ApiError ? error.message : 'Could not move this booking.')
    } finally {
      setMoveBusy(false)
    }
  }

  return (
    <>
      <Drawer
        open={open}
        onClose={onClose}
        width="lg"
        title={booking ? booking.tenant_name : 'Deployment'}
        eyebrow={
          booking ? (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="badge bg-canvas tnum text-ink-muted ring-1 ring-line">
                {booking.booking_reference}
              </span>
              <BookingStatusBadge status={booking.status} />
              {booking.is_emergency ? <EmergencyBadge /> : null}
              {booking.is_locked && booking.status !== 'CANCELLED' ? <LockBadge /> : null}
            </div>
          ) : null
        }
        subtitle={
          booking ? (
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="inline-flex items-center gap-1.5">
                <Calendar className="size-4" />
                {formatDate(booking.deployment_date)}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Clock className="size-4" />
                {booking.slot_label} · {booking.slot_time}
              </span>
            </span>
          ) : undefined
        }
        footer={
          booking ? (
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs text-ink-muted">
                {historicalReadOnly
                  ? 'Historical record: past deployment data is read-only for everyone, including administrators.'
                  : isAdmin
                    ? 'Administrator: future/current records can be edited, moved, assigned, documented or cancelled.'
                    : ownsBooking
                    ? 'Verified as the booking owner for this session.'
                    : isAssigned
                      ? 'Assigned RM user: you can start work and provide the Change No.'
                      : 'Only the booking owner or an assigned RM user can access this change record.'}
              </p>
              {/* Owner and administrator get Edit | Reschedule | Cancel.
                  Anyone else (an assigned RM user) can only view. */}
              <div className="flex gap-2">
                {canAct && !publicLocked ? (
                  <>
                    <button type="button" className="btn-primary" onClick={() => onEdit(booking)}>
                      <Pencil className="size-4" />
                      Edit
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => setRescheduleOpen(true)}
                    >
                      <Calendar className="size-4" />
                      Reschedule
                    </button>
                    <button
                      type="button"
                      className="btn-danger"
                      onClick={() => setConfirmCancel(true)}
                    >
                      <Trash className="size-4" />
                      Cancel
                    </button>
                  </>
                ) : (
                  <span className="badge bg-canvas text-ink-muted ring-1 ring-line">View only</span>
                )}
              </div>
            </div>
          ) : undefined
        }
      >
        {loading || !booking ? (
          <div className="flex items-center justify-center gap-3 py-16 text-sm text-ink-muted">
            <Spinner className="size-5" />
            Loading booking…
          </div>
        ) : (
          <div className="space-y-6">
            {booking.is_past ? (
              <div className="flex items-start gap-3 rounded-xl border border-slate-300 bg-slate-50 p-4">
                <Lock className="mt-0.5 size-5 shrink-0 text-slate-600" />
                <div>
                  <p className="text-sm font-semibold text-ink">Historical record · read-only</p>
                  <p className="mt-0.5 text-sm text-ink-muted">
                    This deployment date has passed. No user or administrator can edit, move, cancel, reassign, change status, start work, change the Change No., or modify attachments.
                  </p>
                </div>
              </div>
            ) : null}

            {publicLocked && !booking.is_past && booking.status !== 'CANCELLED' ? (
              <div className="flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
                <Lock className="mt-0.5 size-5 shrink-0 text-slate-500" />
                <div>
                  <p className="text-sm font-semibold text-ink">Booking locked</p>
                  <p className="mt-0.5 text-sm text-ink-muted">
                    This slot was manually frozen by an administrator. Normal users cannot edit or cancel the booking while it is frozen; an administrator can unfreeze it from the schedule board.
                  </p>
                </div>
              </div>
            ) : null}

            {booking.status === 'CANCELLED' ? (
              <div className="flex items-start gap-3 rounded-xl border border-line bg-canvas p-4">
                <Alert className="mt-0.5 size-5 shrink-0 text-ink-muted" />
                <div>
                  <p className="text-sm font-semibold text-ink">This booking was cancelled</p>
                  <p className="mt-0.5 text-sm text-ink-muted">
                    {formatTimestamp(booking.cancelled_at, timezone)} · the slot has been released.
                  </p>
                </div>
              </div>
            ) : null}

            <dl className="grid grid-cols-[9rem_1fr] gap-x-4">
              <Row label="Tenant">{booking.tenant_name}</Row>
              <Row label="Environment">{booking.environment}</Row>
              <Row label="Technology">{booking.technology}</Row>
              <Row label="Jira No.">
                {booking.jira_url ? (
                  <a
                    href={booking.jira_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex items-center gap-1 font-medium text-brand-600 hover:underline"
                  >
                    {booking.jira_number ?? 'Not provided'}
                    <LinkIcon className="size-3.5" />
                  </a>
                ) : (
                  booking.jira_number ?? 'Not provided'
                )}
              </Row>
              <Row label="Change No.">{booking.change_number ?? 'Pending RM update'}</Row>
              <Row label="Assigned RM users">
                {booking.assigned_users.length ? booking.assigned_users.map((u) => u.full_name).join(', ') : 'Not assigned'}
              </Row>
              <Row label="Requester">
                <span className="inline-flex flex-wrap items-center gap-x-2">
                  <User className="size-3.5 text-ink-muted" />
                  {booking.requester_name}
                  <span className="text-ink-muted">{booking.requester_email}</span>
                  {booking.requester_phone ? (
                    <span className="text-ink-muted">{booking.requester_phone}</span>
                  ) : null}
                </span>
              </Row>
              <Row label="Verifier">
                <span className="inline-flex flex-wrap items-center gap-x-2">
                  {booking.verifier_name}
                  <span className="text-ink-muted">{booking.verifier_email}</span>
                </span>
              </Row>
              <Row label="Git repository">
                <a
                  href={booking.git_repository}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="break-all text-brand-600 hover:underline"
                >
                  {booking.git_repository}
                </a>
              </Row>
              <Row label="Impacted region">{booking.impacted_region}</Row>
              <Row label="Justification">{booking.justification}</Row>
              <Row label="Implementation">{booking.implementation_summary}</Row>
              {booking.deployment_description ? (
                <Row label="Description">{booking.deployment_description}</Row>
              ) : null}
              {booking.additional_comments ? (
                <Row label="Comments">{booking.additional_comments}</Row>
              ) : null}
              {booking.is_emergency ? (
                <>
                  <Row label="Emergency reason">{booking.emergency_reason ?? '—'}</Row>
                  <Row label="Justification">{booking.business_justification ?? '—'}</Row>
                  <Row label="Approver">{booking.emergency_approver ?? '—'}</Row>
                  <Row label="Approval ref.">{booking.emergency_approval_reference ?? '—'}</Row>
                </>
              ) : null}
              <Row label="Created">{formatTimestamp(booking.created_at, timezone)}</Row>
              <Row label="Last modified">{formatTimestamp(booking.updated_at, timezone)}</Row>
            </dl>

            {isAdmin && !booking.is_past ? (
              <section className="rounded-xl border border-line bg-canvas/50 p-4">
                <h3 className="text-sm font-semibold text-ink">Assign RM team users</h3>
                <p className="mt-1 text-xs text-ink-muted">Assigned users can open this CRQ and provide the separate Change No. when they start work.</p>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  {assignmentUsers.map((user) => (
                    <label key={user.id} className="flex items-center gap-2 rounded-lg border border-line bg-white px-3 py-2 text-sm">
                      <input
                        type="checkbox"
                        checked={selectedAssignees.includes(user.id)}
                        onChange={(event) => setSelectedAssignees((current) => event.target.checked ? [...current, user.id] : current.filter((id) => id !== user.id))}
                      />
                      <span>{user.full_name} <span className="text-ink-muted">({user.username})</span></span>
                    </label>
                  ))}
                </div>
                <button type="button" className="btn-primary mt-3" disabled={assignmentBusy || !selectedAssignees.length} onClick={() => void saveAssignments()}>
                  {assignmentBusy ? <Spinner className="size-4" /> : null}
                  Save RM assignment
                </button>
              </section>
            ) : null}

            {(isAssigned || isAdmin) && !booking.is_past && booking.status !== 'CANCELLED' ? (
              <section className="rounded-xl border border-line bg-canvas/50 p-4">
                <h3 className="text-sm font-semibold text-ink">Start RM work</h3>
                <p className="mt-1 text-xs text-ink-muted">Jira No. was supplied during slot booking. Enter the separate Change No. when work begins.</p>
                <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                  <input
                    className="field flex-1"
                    value={changeNumber}
                    onChange={(event) => setChangeNumber(event.target.value)}
                    placeholder="CHG0123456"
                    maxLength={64}
                  />
                  <button type="button" className="btn-primary" disabled={workBusy} onClick={() => void startWork()}>
                    {workBusy ? <Spinner className="size-4" /> : null}
                    {booking.change_number ? 'Update Change No.' : 'Start work'}
                  </button>
                </div>
                {workError ? <p className="mt-2 text-xs font-medium text-rose-600">{workError}</p> : null}
              </section>
            ) : null}

            <DocumentReadinessPanel readiness={booking.documents} />

            <section>
              <h3 className="mb-3 text-sm font-semibold text-ink">Attachments</h3>
              <DocumentUploader
                booking={booking}
                settings={settings}
                isAdmin={isAdmin}
                canManage={ownsBooking}
                readOnly={booking.is_past || !canAct || publicLocked}
                onUpdated={() => onChanged()}
              />
            </section>
          </div>
        )}
      </Drawer>

      {booking ? (
        <Modal
          open={moveOpen}
          onClose={() => setMoveOpen(false)}
          title={booking.is_emergency ? 'Move emergency CRQ' : 'Move / reschedule deployment'}
          description="Administrators can move an active CRQ to a current or future date. Past deployment records are immutable."
          size="md"
          footer={
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-secondary" onClick={() => setMoveOpen(false)} disabled={moveBusy}>
                Cancel
              </button>
              <button type="button" className="btn-primary" onClick={() => void moveBooking()} disabled={moveBusy}>
                {moveBusy ? <Spinner className="size-4" /> : null}
                Move CRQ
              </button>
            </div>
          }
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <div className={booking.is_emergency ? 'sm:col-span-2' : ''}>
              <label className="field-label" htmlFor="admin-move-date">New deployment date</label>
              <input
                id="admin-move-date"
                type="date"
                className="field"
                value={moveDate}
                onChange={(event) => setMoveDate(event.target.value)}
              />
              <p className="mt-1 text-xs text-ink-muted">Past dates are never allowed. Administrators may override other future date restrictions when operationally required.</p>
            </div>
            {!booking.is_emergency ? (
              <div>
                <label className="field-label" htmlFor="admin-move-slot">New slot</label>
                <select
                  id="admin-move-slot"
                  className="field"
                  value={moveSlot}
                  onChange={(event) => setMoveSlot(event.target.value)}
                >
                  <option value="">Select slot</option>
                  {moveSlots.map((slot) => (
                    <option key={slot.slot_number} value={slot.slot_number}>
                      {slot.name} · {slot.start_time.slice(0, 5)}-{slot.end_time.slice(0, 5)}
                      {slot.enabled ? '' : ' · disabled (admin allowed)'}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
          </div>
          {moveError ? <p className="mt-3 text-xs font-medium text-rose-600">{moveError}</p> : null}
        </Modal>
      ) : null}

      <RescheduleModal
        open={rescheduleOpen}
        onClose={() => setRescheduleOpen(false)}
        booking={booking}
        onMoveEmergency={isAdmin ? () => void openMoveDialog() : undefined}
        onDone={onChanged}
      />

      {booking ? (
        <ConfirmationModal
          open={confirmCancel}
          onClose={() => setConfirmCancel(false)}
          onConfirm={() => void cancel()}
          title="Cancel this booking?"
          description="Are you sure you want to cancel this booking? The deployment slot will become available again."
          facts={[
            { label: 'Tenant', value: booking.tenant_name },
            { label: 'JIRA', value: booking.jira_number ?? 'Not provided' },
            { label: 'Date', value: formatDate(booking.deployment_date) },
            { label: 'Slot', value: `${booking.slot_label} · ${booking.slot_time}` },
          ]}
          note="The booking record and its history are kept; only the slot is released."
          confirmLabel="Cancel booking"
          cancelLabel="Keep booking"
          busy={busy}
        >
        </ConfirmationModal>
      ) : null}
    </>
  )
}
