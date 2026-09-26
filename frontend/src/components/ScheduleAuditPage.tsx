import type { BookingDetail } from '../types'
import { formatDate } from '../utils/dates'
import { AuditHistory } from './AuditHistory'
import { ChangePageShell } from './ChangePageShell'
import { Calendar, Clock, Spinner } from './Icons'
import { SchedulePageNav } from './SchedulePageNav'
import { BookingStatusBadge, EmergencyBadge, LockBadge } from './StatusBadge'

export function ScheduleAuditPage({ booking, loading, timezone, onClose }: {
  booking: BookingDetail | null
  loading: boolean
  timezone: string
  onClose: () => void
}) {
  return (
    <ChangePageShell
      open
      onClose={onClose}
      title={booking ? `${booking.tenant_name} · ${booking.change_number ?? booking.booking_reference}` : 'Schedule audit'}
      eyebrow={booking ? <div className="flex flex-wrap items-center gap-1.5">
        <span className="badge bg-canvas tnum text-ink-muted ring-1 ring-line">Schedule No. {booking.booking_reference}</span>
        <BookingStatusBadge status={booking.status} />
        {booking.is_emergency ? <EmergencyBadge /> : null}
        {booking.is_locked && booking.status !== 'CANCELLED' ? <LockBadge /> : null}
      </div> : null}
      subtitle={booking ? <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="inline-flex items-center gap-1.5"><Calendar className="size-4" />{formatDate(booking.deployment_date)}</span>
        <span className="inline-flex items-center gap-1.5"><Clock className="size-4" />{booking.slot_label}{booking.slot_time ? ` · ${booking.slot_time}` : ''}</span>
      </span> : undefined}
      navigation={booking ? <SchedulePageNav reference={booking.booking_reference} active="audit" /> : undefined}
      footer={booking ? <p className="text-xs text-ink-muted">This timeline is append-only. Comments remain in the schedule conversation; audit history records the operational and administrative changes made to the schedule.</p> : undefined}
    >
      {loading || !booking ? <div className="flex items-center justify-center gap-3 py-16 text-sm text-ink-muted"><Spinner className="size-5" />Loading schedule audit…</div> : (
        <section className="card p-5 sm:p-6">
          <div className="mb-5">
            <h2 className="text-lg font-bold text-ink">History</h2>
            <p className="mt-1 text-sm text-ink-muted">Newest activity appears first. Expand an event to inspect the exact before/after values.</p>
          </div>
          <AuditHistory bookingId={booking.id} timezone={timezone} scoped refreshKey={booking.updated_at} />
        </section>
      )}
    </ChangePageShell>
  )
}
