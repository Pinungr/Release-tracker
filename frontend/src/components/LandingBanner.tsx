import type { Schedule } from '../types'
import { Calendar } from './Icons'

/**
 * A tenant's landing notice.
 *
 * Tenants land on the nearest deployment week — even a fully booked one — so
 * they can see how busy the RM team already is. This points them at the next
 * free slot, with a shortcut when it sits in a later week.
 */
export function LandingBanner({
  schedule,
  onGoToWeek,
}: {
  schedule: Schedule
  onGoToWeek: (weekStart: string) => void
}) {
  if (!schedule.landing_message) return null
  const next = schedule.next_available

  return (
    <div role="status" className="card flex flex-wrap items-center gap-3 p-3">
      <p className="flex-1 text-sm text-ink-muted">{schedule.landing_message}</p>
      {next && next.week_start !== schedule.week_start ? (
        <button type="button" className="btn-primary btn-sm" onClick={() => onGoToWeek(next.week_start)}>
          <Calendar className="size-3.5" />
          Go to {next.weekday.slice(0, 3)} {next.date_label}
        </button>
      ) : null}
    </div>
  )
}
