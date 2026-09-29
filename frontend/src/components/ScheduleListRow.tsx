import type { ScheduleListItem } from '../types'
import { formatDate } from '../utils/dates'
import { BookingStatusBadge, EmergencyBadge } from './StatusBadge'

/**
 * One schedule in tenant search or history. Clicking opens the normal record,
 * where the usual permissions decide what the viewer may do.
 */
export function ScheduleListRow({
  schedule,
  onOpen,
  showTenant = false,
}: {
  schedule: ScheduleListItem
  onOpen: (id: number, bookingReference?: string) => void
  showTenant?: boolean
}) {
  const reference = [schedule.change_number && `Change ${schedule.change_number}`, schedule.jira_number && `Jira ${schedule.jira_number}`]
    .filter(Boolean)
    .join(' · ')
  return (
    <button
      type="button"
      className="grid w-full gap-x-4 gap-y-1 rounded-lg border border-line bg-surface p-3 text-left transition-colors hover:bg-canvas sm:grid-cols-[8rem_9rem_minmax(0,1fr)_auto] sm:items-center"
      onClick={() => onOpen(schedule.id, schedule.booking_reference)}
    >
      <strong className="text-sm text-brand-700">{schedule.booking_reference}</strong>
      <span className="text-sm tnum text-ink">
        {formatDate(schedule.deployment_date)}
        <span className="block text-xs text-ink-muted">{schedule.is_emergency ? 'Emergency queue' : `Slot ${schedule.slot_number}`}</span>
      </span>
      <span className="min-w-0 text-xs text-ink-muted">
        {showTenant ? <span className="block text-sm font-medium text-ink">{schedule.tenant_name}</span> : null}
        <span className="block truncate">
          Release Manager: <span className="text-ink">{schedule.release_managers.length ? schedule.release_managers.join(', ') : 'Not assigned'}</span>
        </span>
        {reference ? <span className="block truncate">{reference}</span> : null}
      </span>
      <span className="flex flex-wrap gap-1.5 sm:justify-end">
        {schedule.is_emergency ? <EmergencyBadge /> : null}
        <BookingStatusBadge status={schedule.status} />
      </span>
    </button>
  )
}
