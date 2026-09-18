import { useEffect, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { AuditEvent } from '../types'
import { formatTimestamp } from '../utils/dates'
import { titleCase } from '../utils/format'
import { History, Shield, Spinner, User } from './Icons'

interface AuditHistoryProps {
  timezone: string
  bookingId?: number
}

function ValueList({ label, values }: { label: string; values: Record<string, unknown> }) {
  // Defensive: the API never writes secrets to the audit trail, but the
  // renderer refuses to display anything that looks like one anyway.
  const entries = Object.entries(values).filter(
    ([key]) => !/pass|secret|token|hash/i.test(key),
  )
  if (entries.length === 0) return null
  return (
    <div className="mt-1">
      <span className="text-[11px] font-semibold tracking-wide text-ink-muted uppercase">
        {label}
      </span>
      <ul className="mt-0.5 space-y-0.5">
        {entries.map(([key, value]) => (
          <li key={key} className="text-xs break-words text-ink-muted">
            <span className="font-medium text-ink">{titleCase(key)}:</span>{' '}
            {value === null || value === '' ? '—' : String(value)}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function AuditHistory({ timezone, bookingId }: AuditHistoryProps) {
  const [events, setEvents] = useState<AuditEvent[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setEvents(null)
    setError(null)
    api
      .getAudit(bookingId)
      .then((result) => active && setEvents(result))
      .catch((caught) => active && setError(caught instanceof ApiError ? caught.message : 'Failed.'))
    return () => {
      active = false
    }
  }, [bookingId])

  if (error) return <p className="text-sm text-rose-600">{error}</p>

  if (!events) {
    return (
      <div className="flex items-center gap-2 py-8 text-sm text-ink-muted">
        <Spinner className="size-4" />
        Loading history…
      </div>
    )
  }

  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 py-10 text-center">
        <History className="size-6 text-ink-muted" />
        <p className="text-sm text-ink-muted">No audit events recorded yet.</p>
      </div>
    )
  }

  return (
    <ol className="space-y-2">
      {events.map((event) => (
        <li key={event.id} className="rounded-lg border border-line p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="badge bg-canvas text-ink ring-1 ring-line">
              {titleCase(event.event_type)}
            </span>
            {event.booking_reference ? (
              <span className="text-xs tnum text-ink-muted">{event.booking_reference}</span>
            ) : null}
            <span className="ml-auto text-xs text-ink-muted">
              {formatTimestamp(event.created_at, timezone)}
            </span>
          </div>

          <p className="mt-1.5 flex flex-wrap items-center gap-x-2 text-xs text-ink-muted">
            {event.actor_type === 'ADMIN' ? (
              <Shield className="size-3.5" />
            ) : (
              <User className="size-3.5" />
            )}
            <span className="font-medium text-ink">
              {event.admin_username
                ? `Administrator ${event.admin_username}`
                : (event.requester_email ?? 'System')}
            </span>
            <span>({event.actor_type.toLowerCase()})</span>
          </p>

          {event.override_reason ? (
            <p className="mt-1.5 rounded-md bg-amber-50 px-2 py-1 text-xs text-amber-900">
              Override reason: {event.override_reason}
            </p>
          ) : null}

          {event.old_values ? <ValueList label="Before" values={event.old_values} /> : null}
          {event.new_values ? <ValueList label="After" values={event.new_values} /> : null}
        </li>
      ))}
    </ol>
  )
}
