import type { DayView, SlotView } from '../types'
import { DeploymentSlot, SLOT_GRID } from './DeploymentSlot'
import { Lock, Minus, Plus, Sun, Unlock } from './Icons'

interface DayScheduleProps {
  day: DayView
  today: string
  isAdmin: boolean
  readOnly?: boolean
  myBookingIds: Set<number>
  visibleSlots: SlotView[]
  filtered: boolean
  onBook: (day: DayView, slot: SlotView) => void
  onBookEmergency: (day: DayView) => void
  onOpenBooking: (bookingId: number, bookingReference?: string) => void
  onToggleFreeze: (day: DayView, slot: SlotView) => void
  onToggleLock?: (day: DayView, slot: SlotView | null) => void
  onAdjustCapacity: (day: DayView, delta: 1 | -1) => void
}

const COLUMNS = ['Slot', 'Time', 'Tenant', 'Change No. | Jira No.', 'Verifier', 'Status', 'Docs', '']

export function DaySchedule({
  day,
  today,
  isAdmin,
  readOnly = false,
  myBookingIds,
  visibleSlots,
  filtered,
  onBook,
  onBookEmergency,
  onOpenBooking,
  onToggleFreeze,
  onToggleLock,
  onAdjustCapacity,
}: DayScheduleProps) {
  // Treat the API's authoritative `today` value as a second guard. This keeps
  // historical scheduling actions hidden even if an older response has a stale
  // `is_past` flag. Backend mutation endpoints still enforce the same rule.
  const isHistorical = day.is_past || day.day <= today

  const usage = day.regular_slots_total
    ? `${day.regular_slots_used} / ${day.regular_slots_total}`
    : '0 / 0'

  return (
    <section
      className={`card overflow-hidden transition-shadow ${
        day.is_today ? 'ring-2 ring-brand-500/30' : ''
      } ${isHistorical ? 'opacity-75' : ''}`}
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

        {day.custom_slot_count !== null ? (
          <span className="tooltip-host">
            <span className="badge bg-slate-100 text-slate-600 ring-1 ring-slate-200">
              {day.custom_slot_count} custom slot{day.custom_slot_count === 1 ? '' : 's'}
            </span>
            <span className="tooltip">
              The Owner or a Release Manager changed the number of normal slots on this date. Every other date
              still follows the configured default.
            </span>
          </span>
        ) : null}

        {day.automatic_lock ? (
          <span className="tooltip-host">
            {day.date_unlocked ? (
              <span className="badge bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200">
                <Unlock className="size-3" /> {isHistorical ? 'Uploads unlocked' : 'Unlocked'}
              </span>
            ) : (
              <span className="badge bg-slate-100 text-slate-600 ring-1 ring-slate-200">
                <Lock className="size-3" /> {isHistorical ? 'Uploads locked' : 'Automatic lock'}
              </span>
            )}
            <span className="tooltip">
              {isHistorical
                ? 'Only additional document uploads can be unlocked for today and the previous seven days. Scheduling remains closed.'
                : day.date_unlocked
                ? 'The Owner or a Release Manager lifted the automatic lock for this whole date. Manual slot freezes still apply.'
                : 'Inside the automatic lock window. Only the Owner or a Release Manager can unlock it.'}
            </span>
          </span>
        ) : null}

        <span className="ml-auto text-xs font-semibold tnum text-ink-muted">
          Slots used: <span className="text-ink">{usage}</span>
        </span>

        {isAdmin && !readOnly && day.automatic_lock && onToggleLock ? (
          <button
            type="button"
            className="btn-secondary btn-sm"
            onClick={() => onToggleLock(day, null)}
            title={isHistorical ? 'Control additional document uploads only; scheduling remains closed' : day.date_unlocked ? 'Return this date to the automatic lock' : 'Lift the automatic lock for every slot and the emergency queue on this date'}
          >
            {day.date_unlocked ? <Lock className="size-3.5" /> : <Unlock className="size-3.5" />}
            {day.date_unlocked ? 'Restore lock' : isHistorical ? 'Unlock uploads for date' : 'Unlock date'}
          </button>
        ) : null}

        {/* Normal slot capacity for this one date. Emergency changes have
            their own queue below and are never affected by these. */}
        {isAdmin && !isHistorical ? (
          <span className="inline-flex items-center gap-1">
            <button
              type="button"
              className="btn-secondary btn-sm px-1.5"
              title="Remove a normal deployment slot from this date"
              aria-label={`Remove a slot from ${day.weekday} ${day.date_label}`}
              onClick={() => onAdjustCapacity(day, -1)}
              disabled={day.slots.length === 0}
            >
              <Minus className="size-3.5" />
            </button>
            <button
              type="button"
              className="btn-secondary btn-sm px-1.5"
              title="Add a normal deployment slot to this date"
              aria-label={`Add a slot to ${day.weekday} ${day.date_label}`}
              onClick={() => onAdjustCapacity(day, 1)}
            >
              <Plus className="size-3.5" />
            </button>
          </span>
        ) : null}
      </header>

      {day.holiday?.is_full_day ? (
        <div className="flex flex-col items-start gap-1 border-b border-line bg-amber-50/60 px-4 py-3 sm:flex-row sm:items-center sm:gap-3">
          <span className="text-sm font-semibold tracking-wide text-amber-900 uppercase">
            {day.holiday.name}
          </span>
          <span className="text-sm text-amber-800">
            {isAdmin
              ? isHistorical
                ? 'Scheduling on this past/current date stays protected. Recent dates may unlock extra uploads; admins can close active records.'
                : 'Normal deployment slots are unavailable. The separate emergency queue follows date protection.'
              : 'Holiday — RM team unavailable for normal deployments.'}
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
              isHistorical={isHistorical}
              isMine={slot.booking ? myBookingIds.has(slot.booking.id) : false}
              isAdmin={isAdmin}
              readOnly={readOnly}
              onBook={onBook}
              onOpenBooking={onOpenBooking}
              onToggleFreeze={onToggleFreeze}
              onToggleLock={onToggleLock}
            />
          ))
        )}
      </div>

      {(isAdmin || day.emergency_bookings.length > 0) ? (
      <section className="border-t border-orange-200 bg-orange-50/50 p-4" aria-label="Emergency change queue">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-bold text-orange-950">Emergency change queue</h3>
          <span className="badge bg-orange-100 text-orange-800">{day.emergency_bookings.length}</span>
          <span className="text-xs font-semibold tracking-wide text-orange-800/80 uppercase">
            Owner / Release Manager only
          </span>
          {isAdmin && !isHistorical ? (
            <button
              type="button"
              className="btn-secondary btn-sm ml-auto"
              onClick={() => onBookEmergency(day)}
            >
              <Plus className="size-3.5" /> Add emergency CR
            </button>
          ) : null}
        </div>
        {day.emergency_bookings.length ? (
          <div className="mt-3 space-y-2">
            {day.emergency_bookings.map((booking) => (
              <button key={booking.id} type="button" className="flex w-full items-center gap-3 rounded-lg border border-orange-200 bg-white p-3 text-left" onClick={() => onOpenBooking(booking.id, booking.booking_reference)}>
                <span className="font-semibold text-orange-950">{booking.booking_reference}</span>
                <span className="text-sm text-ink">{booking.tenant_name}</span>
                <span className="text-sm text-ink-muted">{booking.change_number ?? 'Pending'} | {booking.jira_number ?? 'Pending'}</span>
              </button>
            ))}
          </div>
        ) : <p className="mt-2 text-sm text-orange-900/70">No emergency changes scheduled for this date.</p>}
      </section>
      ) : null}

    </section>
  )
}
