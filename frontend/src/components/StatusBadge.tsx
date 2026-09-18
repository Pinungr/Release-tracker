import type { BookingStatus, SlotState } from '../types'
import { Check, Lock, Siren, Sun } from './Icons'

/** One place defines the status colour language used across the board. */
const BOOKING_STYLES: Record<BookingStatus, string> = {
  BOOKED: 'bg-brand-50 text-brand-700 ring-1 ring-brand-100',
  LOCKED: 'bg-slate-100 text-slate-600 ring-1 ring-slate-200',
  COMPLETED: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100',
  CANCELLED: 'bg-slate-100 text-slate-500 ring-1 ring-slate-200',
  VALIDATION_PENDING: 'bg-amber-50 text-amber-700 ring-1 ring-amber-100',
  SUCCESSFUL: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100',
  FAILED: 'bg-rose-50 text-rose-700 ring-1 ring-rose-100',
  ROLLED_BACK: 'bg-orange-50 text-orange-700 ring-1 ring-orange-100',
}

export function BookingStatusBadge({ status }: { status: BookingStatus }) {
  return (
    <span className={`badge ${BOOKING_STYLES[status]}`}>
      {status === 'COMPLETED' ? <Check className="size-3" /> : null}
      {status.replace(/_/g, ' ')}
    </span>
  )
}

export function SlotStateBadge({ state }: { state: SlotState }) {
  switch (state) {
    case 'AVAILABLE':
      return <span className="badge bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100">Available</span>
    case 'EMERGENCY_AVAILABLE':
      return (
        <span className="badge bg-orange-50 text-orange-700 ring-1 ring-orange-200">
          <Siren className="size-3" />
          Emergency
        </span>
      )
    case 'HOLIDAY':
      return (
        <span className="badge bg-amber-50 text-amber-800 ring-1 ring-amber-200">
          <Sun className="size-3" />
          Holiday
        </span>
      )
    case 'DISABLED':
      return (
        <span className="badge bg-slate-100 text-slate-500 ring-1 ring-slate-200">
          <Lock className="size-3" />
          Closed
        </span>
      )
    default:
      return null
  }
}

export function LockBadge({ label = 'Locked' }: { label?: string }) {
  return (
    <span className="badge bg-slate-100 text-slate-600 ring-1 ring-slate-200">
      <Lock className="size-3" />
      {label}
    </span>
  )
}

export function EmergencyBadge() {
  return (
    <span className="badge bg-orange-100 text-orange-800 ring-1 ring-orange-200">
      <Siren className="size-3" />
      Emergency change
    </span>
  )
}

export function MineBadge() {
  return (
    <span className="badge bg-teal-50 text-teal-700 ring-1 ring-teal-200">My booking</span>
  )
}
