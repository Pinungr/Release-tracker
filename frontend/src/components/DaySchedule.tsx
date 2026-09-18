import type { DayView, SlotView } from '../types'
import { DeploymentSlot, SLOT_GRID } from './DeploymentSlot'
import { Calendar, Plus, Sun } from './Icons'

interface DayScheduleProps {
  day: DayView
  isAdmin: boolean
  myBookingIds: Set<number>
  visibleSlots: SlotView[]
  filtered: boolean
  onBook: (day: DayView, slot: SlotView) => void
  onOpenBooking: (bookingId: number) => void
}

const COLUMNS = ['Slot', 'Time', 'Tenant', 'JIRA', 'Verifier', 'Status', 'Docs', '']

export function DaySchedule({
  day,
  isAdmin,
  myBookingIds,
  visibleSlots,
  filtered,
  onBook,
  onOpenBooking,
}: DayScheduleProps) {
  const usage = day.regular_slots_total
    ? `${day.regular_slots_used} / ${day.regular_slots_total}`
    : '0 / 0'
  const firstFree = day.slots.find((slot) =>
    isAdmin ? slot.bookable_by_admin && !slot.is_emergency : slot.bookable_by_public,
  )
  const noBookings = day.slots.every((slot) => slot.booking === null)

  return (
    <section
      className={`card overflow-hidden transition-shadow ${
        day.is_today ? 'ring-2 ring-brand-500/30' : ''
      } ${day.is_past ? 'opacity-75' : ''}`}
      aria-label={`${day.weekday} ${day.date_label}`}
    >
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-canvas/60 px-4 py-3">
        <div className="flex min-w-0 items-baseline gap-2">
          <h2 className="text-sm font-bold tracking-wide text-ink uppercase">{day.weekday}</h2>
          <span className="text-sm tnum text-ink-muted">{day.date_label}</span>
        </div>

        {day.is_today ? (
          <span className="badge bg-brand-600 text-white">Today</span>
        ) : null}

        {day.holiday ? (
          <span className="badge bg-amber-100 text-amber-900 ring-1 ring-amber-200">
            <Sun className="size-3" />
            {day.holiday.name}
            {day.holiday.is_full_day ? '' : ' (partial)'}
          </span>
        ) : null}

        {day.override ? (
          <span className="tooltip-host">
            <span className="badge bg-slate-100 text-slate-600 ring-1 ring-slate-200">Custom day</span>
            <span className="tooltip">
              {day.override.note ?? 'Slot configuration overridden for this date.'}
            </span>
          </span>
        ) : null}

        <span className="ml-auto text-xs font-semibold tnum text-ink-muted">
          Slots used: <span className="text-ink">{usage}</span>
        </span>
      </header>

      {day.holiday?.is_full_day ? (
        <div className="flex flex-col items-start gap-1 border-b border-line bg-amber-50/60 px-4 py-3 sm:flex-row sm:items-center sm:gap-3">
          <span className="text-sm font-semibold tracking-wide text-amber-900 uppercase">
            {day.holiday.name}
          </span>
          <span className="text-sm text-amber-800">
            No production deployments available.
            {day.holiday.allow_emergency
              ? ' Emergency changes remain open to administrators.'
              : ' Emergency changes are also closed.'}
          </span>
        </div>
      ) : null}

      <div className={`max-lg:hidden border-b border-line px-3 py-2 ${SLOT_GRID}`}>
        {COLUMNS.map((column, index) => (
          <span
            key={`${column}-${index}`}
            className={`text-[11px] font-semibold tracking-wide text-ink-muted uppercase ${
              index === COLUMNS.length - 1 ? 'text-right' : ''
            }`}
          >
            {column}
          </span>
        ))}
      </div>

      <div className="space-y-2 p-3">
        {visibleSlots.length === 0 ? (
          <p className="px-1 py-6 text-center text-sm text-ink-muted">
            {filtered
              ? 'No slots on this day match the current search or filter.'
              : 'No deployment slots are configured for this day.'}
          </p>
        ) : (
          visibleSlots.map((slot) => (
            <DeploymentSlot
              key={slot.slot_number}
              day={day}
              slot={slot}
              isAdmin={isAdmin}
              isMine={slot.booking ? myBookingIds.has(slot.booking.id) : false}
              onBook={onBook}
              onOpenBooking={onOpenBooking}
            />
          ))
        )}
      </div>

      {noBookings && !filtered && !day.holiday?.is_full_day && day.regular_slots_total > 0 ? (
        <div className="flex flex-wrap items-center gap-3 border-t border-line bg-canvas/50 px-4 py-3">
          <Calendar className="size-4 text-ink-muted" />
          <p className="text-sm text-ink-muted">
            No deployments booked yet.{' '}
            <span className="font-medium text-ink">
              {day.regular_slots_total} regular slot
              {day.regular_slots_total === 1 ? '' : 's'} available.
            </span>
          </p>
          {firstFree ? (
            <button
              type="button"
              onClick={() => onBook(day, firstFree)}
              className="btn-primary btn-sm ml-auto"
            >
              <Plus className="size-3.5" />
              Book deployment
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
