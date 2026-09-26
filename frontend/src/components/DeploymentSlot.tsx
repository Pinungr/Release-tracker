import type { DayView, SlotView } from '../types'
import { DocumentReadinessPill } from './DocumentReadiness'
import { Clock, Link as LinkIcon, Lock, Plus, Unlock } from './Icons'
import {
  BookingStatusBadge,
  EmergencyBadge,
  LockBadge,
  MineBadge,
  SlotStateBadge,
} from './StatusBadge'
import { initials, tenantTint } from '../utils/format'

/** Shared grid so the day header and every row stay aligned on desktop. */
export const SLOT_GRID =
  'lg:grid lg:grid-cols-[2.5rem_8.5rem_minmax(7rem,1.2fr)_8rem_minmax(6.5rem,1fr)_6rem_4rem_auto] lg:items-center lg:gap-2'

interface DeploymentSlotProps {
  day: DayView
  slot: SlotView
  isMine: boolean
  isAdmin: boolean
  isHistorical: boolean
  onBook: (day: DayView, slot: SlotView) => void
  onOpenBooking: (bookingId: number, bookingReference?: string) => void
  onToggleFreeze: (day: DayView, slot: SlotView) => void
}

export function edgeFor(slot: SlotView, holiday: boolean, isHistorical: boolean): string {
  if (holiday || slot.state === 'HOLIDAY') return 'border-amber-300 bg-amber-50'
  if (slot.booking?.status === 'COMPLETED') return 'border-violet-300 bg-violet-50'
  if (isHistorical || slot.manually_frozen || slot.booking?.is_locked || (!slot.booking && !slot.bookable)) {
    return 'border-slate-300 bg-slate-100'
  }
  if (slot.booking) return 'border-blue-300 bg-blue-50'
  return 'border-emerald-300 bg-emerald-50 hover:bg-emerald-100'
}

function Cell({
  label,
  children,
  className = '',
}: {
  label: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={`min-w-0 ${className}`}>
      <span className="field-label mb-0.5 lg:hidden">{label}</span>
      {children}
    </div>
  )
}

export function DeploymentSlot({
  day,
  slot,
  isMine,
  isAdmin,
  isHistorical,
  onBook,
  onOpenBooking,
  onToggleFreeze,
}: DeploymentSlotProps) {
  const booking = slot.booking
  // Normal board availability comes from the backend and is the same for Admin and users.
  const canBook = booking === null && !isHistorical && slot.bookable

  return (
    <div
      className={`rounded-lg border px-3 py-3 transition-colors ${SLOT_GRID} ${edgeFor(slot, day.holiday?.is_full_day === true, isHistorical)}`}
    >
      {/* Slot number */}
      <div className="flex items-center justify-between gap-2 lg:block">
        <span className="inline-flex items-center gap-1.5">
          <span className="grid size-7 place-items-center rounded-md bg-surface text-xs font-bold tnum text-ink shadow-sm ring-1 ring-line">
            {slot.slot_number}
          </span>
        </span>
        <span className="lg:hidden">
          {booking ? <BookingStatusBadge status={booking.status} /> : <SlotStateBadge state={slot.state} />}
        </span>
      </div>

      {/* Time */}
      <Cell label="Time" className="mt-2 lg:mt-0">
        <span className="inline-flex items-center gap-1.5 text-sm font-medium tnum text-ink">
          <Clock className="size-3.5 shrink-0 text-ink-muted lg:hidden" />
          {slot.time_label}
        </span>
        <p className="truncate text-xs text-ink-muted">{slot.name}</p>
      </Cell>

      {booking ? (
        <>
          {/* Tenant */}
          <Cell label="Tenant" className="mt-2 lg:mt-0">
            <button
              type="button"
              onClick={() => onOpenBooking(booking.id, booking.booking_reference)}
              className="group flex w-full min-w-0 items-center gap-2 overflow-hidden text-left"
            >
              <span
                className={`grid size-7 shrink-0 place-items-center rounded-md text-[10px] font-bold ${tenantTint(booking.tenant_name)}`}
                aria-hidden="true"
              >
                {initials(booking.tenant_name)}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold text-ink group-hover:text-brand-700 group-hover:underline">
                  {booking.tenant_name}
                </span>
                <span className="block truncate text-xs tnum text-ink-muted">
                  Schedule No. {booking.booking_reference}
                </span>
              </span>
            </button>
          </Cell>

          {/* Change / Jira */}
          <Cell label="Change No. | Jira No." className="mt-2 lg:mt-0">
            <div className="flex min-w-0 items-center gap-1.5 text-sm">
              <span className="truncate font-semibold text-ink">{booking.change_number ?? 'Pending'}</span>
              <span className="text-ink-muted">|</span>
              {booking.jira_url ? (
                <a
                  href={booking.jira_url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="inline-flex min-w-0 items-center gap-1 truncate font-medium text-brand-600 hover:underline"
                >
                  {booking.jira_number ?? 'Pending'}
                  <LinkIcon className="size-3.5 shrink-0" />
                </a>
              ) : (
                <span className="truncate font-medium text-ink">{booking.jira_number ?? 'Pending'}</span>
              )}
            </div>
          </Cell>

          {/* Verifier */}
          <Cell label="Verifier" className="mt-2 lg:mt-0">
            <p className="truncate text-sm text-ink">{booking.verifier_name}</p>
            <p className="truncate text-xs text-ink-muted">{booking.technology}</p>
          </Cell>

          {/* Status */}
          <Cell label="Status" className="mt-2 hidden lg:mt-0 lg:block">
            <BookingStatusBadge status={booking.status} />
          </Cell>

          {/* Documents */}
          <Cell label="Documents" className="mt-2 lg:mt-0">
            <DocumentReadinessPill readiness={booking.documents} />
          </Cell>

          {/* Actions / flags */}
          <div className="mt-3 flex flex-wrap items-center gap-1.5 lg:mt-0 lg:justify-end">
            {isMine ? <MineBadge /> : null}
            {booking.is_emergency ? <EmergencyBadge /> : null}
            {booking.is_locked && booking.status !== 'CANCELLED' && !booking.is_emergency ? (
              <LockBadge />
            ) : null}
            {isAdmin && !isHistorical ? (
              <button
                type="button"
                onClick={() => onToggleFreeze(day, slot)}
                className="btn-secondary btn-sm"
                title={slot.manually_frozen ? 'Allow normal-user changes again' : 'Prevent normal-user changes to this slot'}
              >
                {slot.manually_frozen ? <Unlock className="size-3.5" /> : <Lock className="size-3.5" />}
                {slot.manually_frozen ? 'Unfreeze' : 'Freeze'}
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => onOpenBooking(booking.id, booking.booking_reference)}
              className="btn-secondary btn-sm"
            >
              Details
            </button>
          </div>
        </>
      ) : (
        <>
          <Cell label="Status" className="col-span-4 mt-2 lg:col-span-4 lg:mt-0">
            <div className="flex flex-wrap items-center gap-2">
              <SlotStateBadge state={slot.state} />
              {slot.unavailable_reason ? (
                <span className="text-xs text-ink-muted">{slot.unavailable_reason}</span>
              ) : (
                <span className="hidden text-xs text-ink-muted lg:inline">No deployment booked</span>
              )}
            </div>
          </Cell>

          <div className="mt-3 flex flex-wrap items-center gap-2 lg:col-span-2 lg:mt-0 lg:justify-end">
            {isAdmin && !isHistorical ? (
              <button
                type="button"
                onClick={() => onToggleFreeze(day, slot)}
                className="btn-secondary btn-sm"
                title={slot.manually_frozen ? 'Open this slot to normal users' : 'Freeze this slot for normal users'}
              >
                {slot.manually_frozen ? <Unlock className="size-3.5" /> : <Lock className="size-3.5" />}
                {slot.manually_frozen ? 'Unfreeze' : 'Freeze'}
              </button>
            ) : null}
            {canBook ? (
              <button
                type="button"
                onClick={() => onBook(day, slot)}
                className="btn-primary btn-sm"
              >
                <Plus className="size-3.5" />
                Book slot
              </button>
            ) : (
              <span className="tooltip-host">
                <span className="btn-secondary btn-sm cursor-not-allowed opacity-60">
                  <Lock className="size-3.5" />
                  Locked
                </span>
                <span className="tooltip">
                  {slot.unavailable_reason ?? 'This slot is not open for booking.'}
                </span>
              </span>
            )}
          </div>
        </>
      )}
    </div>
  )
}
