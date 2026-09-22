import { useMemo } from 'react'
import type { DayView, FilterKey, Schedule, SlotView } from '../types'
import { DaySchedule } from './DaySchedule'
import { Spinner } from './Icons'

interface WeeklyScheduleProps {
  schedule: Schedule | null
  loading: boolean
  isAdmin: boolean
  myBookingIds: Set<number>
  query: string
  filter: FilterKey
  onBook: (day: DayView, slot: SlotView) => void
  onBookEmergency: (day: DayView) => void
  onOpenBooking: (bookingId: number) => void
  onToggleFreeze: (day: DayView, slot: SlotView) => void
  onAdjustCapacity: (day: DayView, delta: 1 | -1) => void
}

/**
 * Search and filter are applied to the week the backend already returned, so
 * navigating weeks stays a single request and typing costs nothing.
 */
export function matchesSearch(slot: SlotView, query: string): boolean {
  if (!query.trim()) return true
  const needle = query.trim().toLowerCase()
  const booking = slot.booking
  if (!booking) return false
  return [
    booking.tenant_name,
    booking.jira_number,
    booking.verifier_name,
    booking.booking_reference,
    booking.technology,
  ]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(needle))
}

export function matchesFilter(slot: SlotView, filter: FilterKey, mine: Set<number>): boolean {
  const booking = slot.booking
  switch (filter) {
    case 'ALL':
      return true
    case 'AVAILABLE':
      return !booking && slot.state === 'AVAILABLE'
    case 'BOOKED':
      return Boolean(booking)
    case 'MINE':
      return Boolean(booking && mine.has(booking.id))
    case 'EMERGENCY':
      return Boolean(booking?.is_emergency)
    case 'LOCKED':
      return Boolean(booking?.is_locked)
    case 'MISSING_DOCS':
      return Boolean(booking && !booking.documents.complete)
    default:
      if (filter.startsWith('TECH:')) {
        return booking?.technology === filter.slice(5)
      }
      return true
  }
}

export function WeeklySchedule({
  schedule,
  loading,
  isAdmin,
  myBookingIds,
  query,
  filter,
  onBook,
  onBookEmergency,
  onOpenBooking,
  onToggleFreeze,
  onAdjustCapacity,
}: WeeklyScheduleProps) {
  const visibleByDay = useMemo(() => {
    if (!schedule) return new Map<string, SlotView[]>()
    return new Map(
      schedule.days.map((day) => [
        day.day,
        day.slots.filter(
          (slot) => matchesSearch(slot, query) && matchesFilter(slot, filter, myBookingIds),
        ),
      ]),
    )
  }, [schedule, query, filter, myBookingIds])

  if (!schedule) {
    return (
      <div className="card flex items-center justify-center gap-3 py-20 text-sm text-ink-muted">
        <Spinner className="size-5" />
        Loading the deployment board…
      </div>
    )
  }

  const filtered = query.trim().length > 0 || filter !== 'ALL'

  return (
    <div className={`space-y-4 transition-opacity ${loading ? 'opacity-60' : ''}`}>
      {schedule.days.map((day) => (
        <DaySchedule
          key={day.day}
          day={day}
          today={schedule.today}
          isAdmin={isAdmin}
          myBookingIds={myBookingIds}
          visibleSlots={visibleByDay.get(day.day) ?? []}
          filtered={filtered}
          onBook={onBook}
          onBookEmergency={onBookEmergency}
          onOpenBooking={onOpenBooking}
          onToggleFreeze={onToggleFreeze}
          onAdjustCapacity={onAdjustCapacity}
        />
      ))}
    </div>
  )
}
