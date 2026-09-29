import type { TenantUpcoming } from '../types'
import { Calendar } from './Icons'
import { ScheduleListRow } from './ScheduleListRow'

/**
 * A tenant's upcoming schedules. The server returns only weeks that hold one
 * of this tenant's schedules, so there are no empty weeks and no other
 * tenants' schedules to hide here.
 */
export function TenantUpcomingResults({
  result,
  onOpen,
}: {
  result: TenantUpcoming
  onOpen: (id: number, bookingReference?: string) => void
}) {
  if (result.weeks.length === 0) {
    return (
      <p role="status" className="text-sm text-ink-muted">
        No upcoming PDS schedules found for <strong className="text-ink">{result.tenant_name}</strong>.
      </p>
    )
  }
  return (
    <div className="space-y-4">
      <h2 className="text-sm font-semibold text-ink">{result.tenant_name} – Upcoming schedules</h2>
      {result.weeks.map((week) => (
        <section key={week.week_start} aria-label={`Week ${week.week_label}`}>
          <h3 className="mb-2 flex items-center gap-2 text-xs font-bold tracking-wide text-ink-muted uppercase">
            <Calendar className="size-3.5" />
            Week: {week.week_label}
            <span className="badge bg-canvas text-ink-muted ring-1 ring-line">{week.schedules.length}</span>
          </h3>
          <div className="space-y-2">
            {week.schedules.map((schedule) => (
              <ScheduleListRow key={schedule.id} schedule={schedule} onOpen={onOpen} />
            ))}
          </div>
        </section>
      ))}
      {result.truncated ? (
        <p className="text-xs text-ink-muted">Showing the nearest schedules only. Use History to browse further.</p>
      ) : null}
    </div>
  )
}
