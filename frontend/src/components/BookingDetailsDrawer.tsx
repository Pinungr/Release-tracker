import { useState } from 'react'
import { api, ApiError } from '../services/api'
import type { BookingDetail, PublicSettings } from '../types'
import { formatDate, formatTimestamp, relativeToNow } from '../utils/dates'
import { DocumentReadinessPanel } from './DocumentReadiness'
import { DocumentUploader } from './DocumentUploader'
import { Drawer } from './Drawer'
import { Alert, Calendar, Clock, Link as LinkIcon, Lock, Pencil, Spinner, Trash, User } from './Icons'
import { ConfirmationModal } from './Modal'
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
  const [overrideReason, setOverrideReason] = useState('')
  const [busy, setBusy] = useState(false)

  const ownsBooking = booking !== null && userId === booking.created_by_user_id

  const canAct = booking !== null && booking.status !== 'CANCELLED' && (isAdmin || ownsBooking)
  const publicLocked = booking !== null && booking.is_locked && !isAdmin

  async function cancel() {
    if (!booking) return
    setBusy(true)
    try {
      await api.cancelBooking(booking.id, {
        override_reason: isAdmin ? overrideReason || null : null,
      })
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
                {isAdmin
                  ? 'Administrator: you can edit or cancel at any time.'
                  : ownsBooking
                    ? 'Verified as the booking owner for this session.'
                    : ownsBooking
                      ? 'You are the authenticated owner of this change record.'
                      : 'Only the authenticated booking owner can manage this change record.'}
              </p>
              <div className="flex gap-2">
                {canAct && !publicLocked ? (
                  <>
                    <button
                      type="button"
                      className="btn-danger"
                      onClick={() => {
                        setOverrideReason('')
                        setConfirmCancel(true)
                      }}
                    >
                      <Trash className="size-4" />
                      Cancel booking
                    </button>
                    <button type="button" className="btn-primary" onClick={() => onEdit(booking)}>
                      <Pencil className="size-4" />
                      Edit booking
                    </button>
                  </>
                ) : null}
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
            {publicLocked && booking.status !== 'CANCELLED' ? (
              <div className="flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
                <Lock className="mt-0.5 size-5 shrink-0 text-slate-500" />
                <div>
                  <p className="text-sm font-semibold text-ink">Booking locked</p>
                  <p className="mt-0.5 text-sm text-ink-muted">
                    Changes are disabled within {settings.booking_freeze_hours} hours of the
                    deployment. Contact an administrator for assistance.
                  </p>
                  {booking.lock_deadline ? (
                    <p className="mt-1 text-xs text-ink-muted">
                      Editing closed {relativeToNow(booking.lock_deadline)} (
                      {formatTimestamp(booking.lock_deadline, timezone)}).
                    </p>
                  ) : null}
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
              <Row label="JIRA change">
                {booking.jira_url ? (
                  <a
                    href={booking.jira_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex items-center gap-1 font-medium text-brand-600 hover:underline"
                  >
                    {booking.jira_change}
                    <LinkIcon className="size-3.5" />
                  </a>
                ) : (
                  booking.jira_change
                )}
              </Row>
              {booking.jira_task ? <Row label="JIRA task">{booking.jira_task}</Row> : null}
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
              <Row label="Implementation">{booking.implementation_summary}</Row>
              <Row label="Description">{booking.deployment_description}</Row>
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

            <DocumentReadinessPanel readiness={booking.documents} />

            <section>
              <h3 className="mb-3 text-sm font-semibold text-ink">Attachments</h3>
              <DocumentUploader
                booking={booking}
                settings={settings}
                isAdmin={isAdmin}
                canManage={ownsBooking}
                readOnly={!canAct || publicLocked}
                onUpdated={() => onChanged()}
              />
            </section>
          </div>
        )}
      </Drawer>

      {booking ? (
        <ConfirmationModal
          open={confirmCancel}
          onClose={() => setConfirmCancel(false)}
          onConfirm={() => void cancel()}
          title="Cancel deployment booking?"
          facts={[
            { label: 'Tenant', value: booking.tenant_name },
            { label: 'JIRA', value: booking.jira_change },
            { label: 'Date', value: formatDate(booking.deployment_date) },
            { label: 'Slot', value: `${booking.slot_label} · ${booking.slot_time}` },
          ]}
          note="This action will release the slot for other tenants."
          confirmLabel="Cancel booking"
          cancelLabel="Keep booking"
          busy={busy}
        >
          {isAdmin && booking.is_locked ? (
            <label className="block">
              <span className="field-label">Override reason</span>
              <input
                className="field"
                value={overrideReason}
                onChange={(event) => setOverrideReason(event.target.value)}
                placeholder="Why is this being cancelled inside the freeze window?"
                maxLength={500}
              />
              <span className="mt-1 block text-xs text-ink-muted">
                Recorded in the audit history.
              </span>
            </label>
          ) : null}
        </ConfirmationModal>
      ) : null}
    </>
  )
}
