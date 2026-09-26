import { useEffect, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { BookingDetail, PublicSettings } from '../types'
import { formatDate, formatTimestamp } from '../utils/dates'
import { DocumentReadinessPanel } from './DocumentReadiness'
import { DocumentUploader } from './DocumentUploader'
import { ChangePageShell } from './ChangePageShell'
import { ChangeActivity } from './ChangeActivity'
import { Alert, Calendar, Clock, Link as LinkIcon, Lock, Pencil, Spinner, Trash, User } from './Icons'
import { ConfirmationModal, Modal } from './Modal'
import { RescheduleModal } from './RescheduleModal'
import { ReleaseManagerAssignee } from './ReleaseManagerAssignee'
import { BookingStatusBadge, EmergencyBadge, LockBadge } from './StatusBadge'
import { useToast } from './ToastNotification'

interface ChangeDetailsPageProps {
  open: boolean
  onClose: () => void
  booking: BookingDetail | null
  loading: boolean
  settings: PublicSettings
  isAdmin: boolean
  timezone: string
  userId: number | null
  onEdit: (booking: BookingDetail) => void
  onClone?: (booking: BookingDetail) => void
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

export function ChangeDetailsPage({
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
  onClone,
}: ChangeDetailsPageProps) {
  const toast = useToast()
  const [confirmCancel, setConfirmCancel] = useState(false)
  const [rescheduleOpen, setRescheduleOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [moveOpen, setMoveOpen] = useState(false)
  const [moveDate, setMoveDate] = useState('')
  const [moveBusy, setMoveBusy] = useState(false)
  const [moveError, setMoveError] = useState<string | null>(null)
  const [changeNumber, setChangeNumber] = useState('')
  const [workBusy, setWorkBusy] = useState(false)
  const [workError, setWorkError] = useState<string | null>(null)
  const [collaboratorOpen, setCollaboratorOpen] = useState(false)
  const [collaboratorSearch, setCollaboratorSearch] = useState('')
  const [collaboratorCandidates, setCollaboratorCandidates] = useState<Array<{ id: number; full_name: string; username: string; email: string; selected: boolean }>>([])
  const [collaboratorSelection, setCollaboratorSelection] = useState<number[]>([])
  const [collaboratorBusy, setCollaboratorBusy] = useState(false)

  const ownsBooking = booking !== null && userId === booking.created_by_user_id
  const canAct = booking?.can_edit ?? false
  const hasLockReason = booking !== null && booking.lock_reason !== 'NONE'
  const isAssigned = booking !== null && userId !== null && booking.assigned_users.some((u) => u.user_id === userId)
  const lockMessages = {
    CURRENT_DATE: 'This booking is locked because deployments scheduled for today are read-only.',
    PAST_DATE: 'This booking is historical and cannot be modified.',
    AUTOMATIC_DATE_FREEZE: 'This deployment date is inside the protected scheduling window.',
    MANUAL_SLOT_FREEZE: 'This slot was manually frozen by the Owner or a Release Manager.',
    NONE: '',
  }

  useEffect(() => {
    setChangeNumber(booking?.change_number ?? '')
    setWorkError(null)
  }, [booking?.id, booking?.change_number, open])

  useEffect(() => {
    if (!collaboratorOpen || !booking || !ownsBooking) return
    const timer = window.setTimeout(() => {
      void api.getCollaboratorCandidates(booking.id, collaboratorSearch).then((rows) => {
        setCollaboratorCandidates(rows)
        setCollaboratorSelection((current) => current.length ? current : booking.collaborators.map((u) => u.user_id))
      }).catch(() => setCollaboratorCandidates([]))
    }, 150)
    return () => window.clearTimeout(timer)
  }, [collaboratorOpen, collaboratorSearch, booking?.id, booking?.collaborators, ownsBooking])

  async function saveCollaborators() {
    if (!booking || !ownsBooking) return
    setCollaboratorBusy(true)
    try {
      await api.setCollaborators(booking.id, collaboratorSelection)
      toast.success('Booking collaborators updated.')
      setCollaboratorOpen(false)
      onChanged()
    } catch (error) {
      toast.error('Could not update collaborators', error instanceof ApiError ? error.message : 'Please try again.')
    } finally {
      setCollaboratorBusy(false)
    }
  }

  async function startWork() {
    if (!booking || !booking.can_start_work) return
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

  async function markCompleted() {
    if (!booking || !isAdmin || !booking.can_edit || (booking.status !== 'IN_PROGRESS' || !booking.work_started_at || !booking.change_number?.trim())) return
    setBusy(true)
    try {
      await api.setBookingStatus(booking.id, 'COMPLETED')
      toast.success('Booking marked as completed.', booking.booking_reference)
      onChanged()
    } catch (error) {
      toast.error('Could not update the status', error instanceof ApiError ? error.message : 'Please try again.')
    } finally {
      setBusy(false)
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
    if (!booking || !booking.is_emergency || !isAdmin || !booking.can_reschedule) return
    setMoveDate(booking.deployment_date)
    setMoveError(null)
    setMoveOpen(true)
  }

  async function moveBooking() {
    if (!booking) return
    if (!moveDate) {
      setMoveError('Select the new deployment date.')
      return
    }
    setMoveBusy(true)
    setMoveError(null)
    try {
      await api.moveBooking(booking.id, {
        deployment_date: moveDate,
        slot_number: null,
        override_reason: null,
      })
      toast.success(
        'Emergency CRQ moved.',
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
      <ChangePageShell
        open={open}
        onClose={onClose}
        width="lg"
        title={booking ? `${booking.tenant_name} · ${booking.change_number ?? booking.booking_reference}` : 'Deployment'}
        eyebrow={
          booking ? (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="badge bg-canvas tnum text-ink-muted ring-1 ring-line">
                Schedule No. {booking.booking_reference}
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
                {hasLockReason && !canAct
                  ? 'Past, current and protected deployment dates are read-only for everyone, including the Owner and Release Managers.'
                  : isAdmin
                    ? 'Owner/Release Manager: actions are available only on editable future records.'
                    : ownsBooking
                    ? 'Verified as the booking owner for this session.'
                    : isAssigned
                      ? 'Assigned Release Manager: authorized documents are available to download; work actions depend on date protection.'
                      : 'Read-only: you can view, clone and comment on this schedule. Only the booking owner or a Release Manager can change it.'}
              </p>
              {/* Owner and Release Managers get Edit | Reschedule | Cancel according to
                  record/date permissions. Start-work requires an explicit Release Manager assignment. */}
              <div className="flex flex-wrap gap-2">
                {onClone && <button type="button" className="btn-secondary" onClick={() => onClone(booking)}>Clone schedule</button>}
                <button type="button" className="btn-secondary" onClick={() => {
                  if (!navigator.clipboard) { toast.error('Copy unavailable', 'Select and copy the Schedule No. shown above.'); return }
                  void navigator.clipboard.writeText(booking.booking_reference).then(() => toast.success('Schedule No. copied')).catch(() => toast.error('Could not copy', 'Select and copy the Schedule No. shown above.'))
                }}>Copy Schedule No.</button>
                {ownsBooking && !booking.is_emergency ? <button type="button" className="btn-secondary" onClick={() => { setCollaboratorSelection(booking.collaborators.map((u) => u.user_id)); setCollaboratorOpen(true) }}>Collaborators</button> : null}
                {canAct ? (
                  <>
                    <button type="button" className="btn-primary" onClick={() => onEdit(booking)}>
                      <Pencil className="size-4" />
                      Edit
                    </button>
                    {booking.can_reschedule ? <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => setRescheduleOpen(true)}
                    >
                      <Calendar className="size-4" />
                      Reschedule
                    </button> : null}
                    {isAdmin && booking.status === 'IN_PROGRESS' && booking.work_started_at && booking.change_number?.trim() ? (
                      <button type="button" className="btn-secondary" disabled={busy} onClick={() => void markCompleted()}>
                        Complete / Close
                      </button>
                    ) : null}
                    {booking.can_cancel ? <button
                      type="button"
                      className="btn-danger"
                      onClick={() => setConfirmCancel(true)}
                    >
                      <Trash className="size-4" />
                      Cancel
                    </button> : null}
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
          <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(18rem,1fr)]">
            {hasLockReason && booking.status !== 'CANCELLED' ? (
              <div className="lg:col-span-2 flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
                <Lock className="mt-0.5 size-5 shrink-0 text-slate-500" />
                <div>
                  <p className="text-sm font-semibold text-ink">Booking locked</p>
                  <p className="mt-0.5 text-sm text-ink-muted">
                    {lockMessages[booking.lock_reason]}
                  </p>
                </div>
              </div>
            ) : null}

            {booking.status === 'CANCELLED' ? (
              <div className="lg:col-span-2 flex items-start gap-3 rounded-xl border border-line bg-canvas p-4">
                <Alert className="mt-0.5 size-5 shrink-0 text-ink-muted" />
                <div>
                  <p className="text-sm font-semibold text-ink">This booking was cancelled</p>
                  <p className="mt-0.5 text-sm text-ink-muted">
                    {formatTimestamp(booking.cancelled_at, timezone)} · the slot has been released.
                  </p>
                </div>
              </div>
            ) : null}

            <dl className="card grid grid-cols-[8rem_1fr] gap-x-4 p-5">
              {booking.cloned_from_reference && <Row label="Cloned from"><a className="text-brand-600 underline" href={`#change/${booking.cloned_from_id}`}>{booking.cloned_from_reference}</a></Row>}
              <Row label="Tenant">{booking.tenant_name}</Row>
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
              <Row label="Assigned Release Manager">
                {booking.assigned_users.length ? booking.assigned_users.map((u) => u.full_name).join(', ') : 'Not assigned'}
              </Row>
              <Row label="Booking collaborators">
                {booking.collaborators.length ? booking.collaborators.map((u) => u.full_name).join(', ') : 'None'}
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

            <aside className="space-y-5">
              <section className="card space-y-3 p-5">
                <h2 className="text-sm font-bold text-ink">Workflow</h2>
                <p className="text-sm text-ink-muted">Assign Release Manager → Start work with Change No. → Complete / Close</p>
                <BookingStatusBadge status={booking.status} />
                <p className="text-sm"><strong>Assigned to:</strong> {booking.assigned_users.map(u => u.full_name).join(', ') || 'Not assigned'}</p>
                <p className="text-xs text-ink-muted">Started: {booking.work_started_at ? formatTimestamp(booking.work_started_at, timezone) : 'Not started'}</p>
              </section>
            {booking.can_assign_rm ? (
              <ReleaseManagerAssignee key={booking.id} booking={booking} onChanged={onChanged} />
            ) : null}

            {booking.can_start_work ? (
              <section className="rounded-xl border border-line bg-canvas/50 p-4">
                <h3 className="text-sm font-semibold text-ink">Start work</h3>
                <p className="mt-1 text-xs text-ink-muted">An assigned Release Manager adds the Change Number when work begins. The Jira reference remains separate.</p>
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

            </aside>
            <div className="lg:col-span-2"><DocumentReadinessPanel readiness={booking.documents} /></div>

            <section className="card p-5 lg:col-span-2">
              <h3 className="mb-3 text-sm font-semibold text-ink">Attachments</h3>
              <DocumentUploader
                booking={booking}
                settings={settings}
                isAdmin={isAdmin}
                canManage={booking.can_manage_attachments}
                readOnly={!booking.can_manage_attachments}
                onUpdated={() => onChanged()}
              />
            </section>
            <div className="lg:col-span-2"><ChangeActivity key={booking.id} bookingId={booking.id} isAdmin={isAdmin} timezone={timezone} revision={JSON.stringify([booking.updated_at, booking.status, booking.assigned_users])} /></div>
          </div>
        )}
      </ChangePageShell>

      {booking ? (
        <Modal
          open={moveOpen}
          onClose={() => setMoveOpen(false)}
          title="Move emergency CRQ"
          description="Move an active CRQ to an unprotected future date. Past, current and protected dates are read-only for the Owner and Release Managers too."
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
            <div className="sm:col-span-2">
              <label className="field-label" htmlFor="admin-move-date">New deployment date</label>
              <input
                id="admin-move-date"
                type="date"
                className="field"
                value={moveDate}
                onChange={(event) => setMoveDate(event.target.value)}
              />
              <p className="mt-1 text-xs text-ink-muted">Past, current and protected dates are never allowed. Emergency changes use a separate queue with no slot number.</p>
            </div>
          </div>
          {moveError ? <p className="mt-3 text-xs font-medium text-rose-600">{moveError}</p> : null}
        </Modal>
      ) : null}

      {booking && ownsBooking ? (
        <Modal
          open={collaboratorOpen}
          onClose={() => setCollaboratorOpen(false)}
          title="Booking collaborators"
          description={`Choose colleagues from ${booking.tenant_name}. Collaborators can edit, reschedule, cancel and manage documents under the same booking rules as you.`}
          size="md"
          footer={
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-secondary" onClick={() => setCollaboratorOpen(false)} disabled={collaboratorBusy}>Cancel</button>
              <button type="button" className="btn-primary" onClick={() => void saveCollaborators()} disabled={collaboratorBusy}>
                {collaboratorBusy ? <Spinner className="size-4" /> : null}
                Save collaborators
              </button>
            </div>
          }
        >
          <label className="field-label" htmlFor="collaborator-search">Search same-tenant colleagues</label>
          <input id="collaborator-search" className="field" value={collaboratorSearch} onChange={(event) => setCollaboratorSearch(event.target.value)} placeholder="Name, username or email" />
          <div className="mt-3 max-h-72 space-y-2 overflow-y-auto">
            {collaboratorCandidates.map((candidate) => (
              <label key={candidate.id} className="flex items-center gap-3 rounded-lg border border-line px-3 py-2 text-sm">
                <input
                  type="checkbox"
                  checked={collaboratorSelection.includes(candidate.id)}
                  onChange={(event) => setCollaboratorSelection((current) => event.target.checked ? [...current, candidate.id] : current.filter((id) => id !== candidate.id))}
                />
                <span><span className="font-medium text-ink">{candidate.full_name}</span><span className="ml-2 text-xs text-ink-muted">@{candidate.username}</span></span>
              </label>
            ))}
            {!collaboratorCandidates.length ? <p className="py-5 text-center text-sm text-ink-muted">No eligible colleagues found in this tenant group.</p> : null}
          </div>
          <p className="mt-3 text-xs text-ink-muted">Only the booking creator can add or remove collaborators. Collaborators cannot delegate access onward.</p>
        </Modal>
      ) : null}

      <RescheduleModal
        open={rescheduleOpen}
        onClose={() => setRescheduleOpen(false)}
        booking={booking}
        onMoveEmergency={isAdmin ? () => void openMoveDialog() : undefined}
        onDone={() => {
          // Return to the board on success, the same way cancelling does, so
          // the moved booking is visible in its new slot straight away.
          onChanged()
          onClose()
        }}
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
