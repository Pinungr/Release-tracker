import type { DayView, SlotView } from '../types'
import { DocumentReadinessPill } from './DocumentReadiness'
import { Clock, Link as LinkIcon, Lock, Plus } from './Icons'
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
  onBook: (day: DayView, slot: SlotView) => void
  onOpenBooking: (bookingId: number) => void
}

function edgeFor(slot: SlotView, isMine: boolean): string {
  if (slot.booking) {
    if (isMine) return 'border-teal-300 bg-teal-50/40 ring-1 ring-teal-200'
    if (slot.booking.is_emergency) return 'border-orange-300 bg-orange-50/50'
    if (slot.booking.status === 'CANCELLED') return 'border-line bg-canvas'
    if (slot.booking.status === 'COMPLETED') return 'border-emerald-200 bg-emerald-50/40'
    return 'border-brand-100 bg-brand-50/40'
  }
  switch (slot.state) {
    case 'AVAILABLE':
      return 'border-emerald-200 bg-emerald-50/40 hover:bg-emerald-50'
    case 'HOLIDAY':
      return 'border-amber-200 bg-amber-50/50'
    default:
      return 'border-line bg-canvas'
  }
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
  onBook,
  onOpenBooking,
}: DeploymentSlotProps) {
  const booking = slot.booking
  const canBook = slot.bookable

  return (
    <div
      className={`rounded-lg border px-3 py-3 transition-colors ${SLOT_GRID} ${edgeFor(slot, isMine)}`}
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
              onClick={() => onOpenBooking(booking.id)}
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
                  {booking.booking_reference}
                </span>
              </span>
            </button>
          </Cell>

          {/* JIRA */}
          <Cell label="JIRA" className="mt-2 lg:mt-0">
            {booking.jira_url ? (
              <a
                href={booking.jira_url}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex max-w-full items-center gap-1 truncate text-sm font-medium text-brand-600 hover:underline"
              >
                {booking.jira_change}
                <LinkIcon className="size-3.5 shrink-0" />
              </a>
            ) : (
              <span className="block truncate text-sm font-medium text-ink">
                {booking.jira_change}
              </span>
            )}
            {booking.jira_task ? (
              <p className="truncate text-xs text-ink-muted">{booking.jira_task}</p>
            ) : null}
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
            <button
              type="button"
              onClick={() => onOpenBooking(booking.id)}
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

          <div className="mt-3 flex items-center gap-2 lg:col-span-2 lg:mt-0 lg:justify-end">
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
