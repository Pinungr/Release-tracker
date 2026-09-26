import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { AuditEvent } from '../types'
import { formatTimestamp } from '../utils/dates'
import { titleCase } from '../utils/format'
import { History, Shield, Spinner, User } from './Icons'

interface AuditHistoryProps {
  timezone: string
  bookingId?: number
  scoped?: boolean
  query?: string
  eventType?: string
  actorType?: 'USER' | 'ADMIN' | 'SYSTEM' | ''
  linkSchedules?: boolean
  refreshKey?: string | number
}

const EVENT_LABELS: Record<string, string> = {
  BOOKING_CREATED: 'Schedule created',
  EMERGENCY_BOOKING_CREATED: 'Emergency schedule created',
  BOOKING_CLONED: 'Schedule cloned',
  BOOKING_EDITED: 'Schedule updated',
  SLOT_CHANGED: 'Schedule moved',
  BOOKING_RESCHEDULED: 'Schedule rescheduled',
  BOOKING_CANCELLED: 'Schedule cancelled',
  BOOKING_DELETED: 'Schedule deleted',
  BOOKING_STATUS_CHANGED: 'Status changed',
  RM_USERS_ASSIGNED: 'Release Manager assigned',
  WORK_STARTED: 'Work started',
  CHANGE_NUMBER_UPDATED: 'Change Number updated',
  DOCUMENT_ADDED: 'Document uploaded',
  DOCUMENT_DELETED: 'Document removed',
  SLOT_MANUALLY_FROZEN: 'Slot frozen',
  SLOT_MANUALLY_UNFROZEN: 'Slot unfrozen',
  SLOT_CONFIG_UPDATED: 'Slot configuration updated',
  SETTINGS_UPDATED: 'Settings updated',
  HOLIDAY_CREATED: 'Holiday created',
  HOLIDAY_UPDATED: 'Holiday updated',
  HOLIDAY_DELETED: 'Holiday deleted',
  TENANT_CREATED: 'Tenant created',
  USER_STATUS_UPDATED: 'User status updated',
  PASSWORD_RESET_BY_ADMIN: 'Password reset',
}

const hiddenKey = (key: string) => /pass|secret|token|hash/i.test(key)

function valueText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (Array.isArray(value)) return value.length ? value.map(valueText).join(', ') : '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function eventLabel(event: AuditEvent) {
  return EVENT_LABELS[event.event_type] ?? titleCase(event.event_type)
}

function eventSummary(event: AuditEvent): string | null {
  const oldValues = event.old_values ?? {}
  const newValues = event.new_values ?? {}
  if (event.event_type === 'DOCUMENT_ADDED') {
    return `${valueText(newValues.filename)} · ${valueText(newValues.category)}`
  }
  if (event.event_type === 'DOCUMENT_DELETED') {
    return `${valueText(oldValues.filename)} · ${valueText(oldValues.category)}`
  }
  if (event.event_type === 'WORK_STARTED') {
    return `Change No. ${valueText(newValues.change_number)}`
  }
  if (event.event_type === 'CHANGE_NUMBER_UPDATED') {
    return `${valueText(oldValues.change_number)} → ${valueText(newValues.change_number)}`
  }
  if (event.event_type === 'BOOKING_STATUS_CHANGED' || event.event_type === 'BOOKING_CANCELLED') {
    return `${valueText(oldValues.status)} → ${valueText(newValues.status)}`
  }
  if (event.event_type === 'BOOKING_RESCHEDULED' || event.event_type === 'SLOT_CHANGED') {
    const oldDate = valueText(oldValues.deployment_date)
    const newDate = valueText(newValues.deployment_date)
    const oldSlot = valueText(oldValues.slot_number)
    const newSlot = valueText(newValues.slot_number)
    return oldDate !== newDate || oldSlot !== newSlot ? `${oldDate} / slot ${oldSlot} → ${newDate} / slot ${newSlot}` : null
  }
  if (event.event_type === 'RM_USERS_ASSIGNED') {
    const before = oldValues.assigned_user_names ?? oldValues.assigned_user_ids
    const after = newValues.assigned_user_names ?? newValues.assigned_user_ids
    return `${valueText(before)} → ${valueText(after)}`
  }
  return null
}

function ChangeDetails({ event }: { event: AuditEvent }) {
  const oldValues = event.old_values ?? {}
  const newValues = event.new_values ?? {}
  const keys = Array.from(new Set([...Object.keys(oldValues), ...Object.keys(newValues)]))
    .filter((key) => !hiddenKey(key))
  if (!keys.length) return null

  return (
    <details className="mt-3 rounded-lg border border-line bg-canvas/50 px-3 py-2">
      <summary className="cursor-pointer text-xs font-semibold text-brand-700">
        View event details
      </summary>
      <div className="mt-3 space-y-2">
        {keys.map((key) => {
          const before = oldValues[key]
          const after = newValues[key]
          const hasBefore = Object.prototype.hasOwnProperty.call(oldValues, key)
          const hasAfter = Object.prototype.hasOwnProperty.call(newValues, key)
          return (
            <div key={key} className="grid gap-1 border-b border-line/60 pb-2 last:border-0 last:pb-0 sm:grid-cols-[11rem_1fr]">
              <span className="text-xs font-semibold text-ink">{titleCase(key)}</span>
              <span className="min-w-0 break-words text-xs text-ink-muted">
                {hasBefore && hasAfter ? (
                  <><span>{valueText(before)}</span><span className="mx-2 text-ink-muted">→</span><span className="font-medium text-ink">{valueText(after)}</span></>
                ) : hasAfter ? (
                  <span className="font-medium text-ink">{valueText(after)}</span>
                ) : (
                  <span>{valueText(before)}</span>
                )}
              </span>
            </div>
          )
        })}
      </div>
    </details>
  )
}

export function AuditHistory({
  timezone,
  bookingId,
  scoped = false,
  query = '',
  eventType = '',
  actorType = '',
  linkSchedules = false,
  refreshKey = '',
}: AuditHistoryProps) {
  const [events, setEvents] = useState<AuditEvent[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [more, setMore] = useState(false)
  const [busy, setBusy] = useState(false)
  const pageSize = scoped ? 50 : 100

  const filterKey = useMemo(() => JSON.stringify([query.trim(), eventType, actorType]), [query, eventType, actorType])

  useEffect(() => {
    let active = true
    setEvents(null)
    setError(null)
    const load = scoped && bookingId
      ? api.getBookingAudit(bookingId)
      : api.getAudit({ bookingId, q: query, eventType, actorType: actorType || undefined, limit: pageSize })
    load
      .then((result) => {
        if (active) {
          setEvents(result)
          setMore(result.length === pageSize)
        }
      })
      .catch((caught) => active && setError(caught instanceof ApiError ? caught.message : 'Could not load audit history.'))
    return () => { active = false }
  }, [bookingId, scoped, filterKey, refreshKey, pageSize])

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
      <div className="flex flex-col items-center gap-2 py-12 text-center">
        <History className="size-7 text-ink-muted" />
        <p className="text-sm font-medium text-ink">No audit events found.</p>
        <p className="text-xs text-ink-muted">Try a different filter or search term.</p>
      </div>
    )
  }

  return (
    <>
      <ol className="relative ml-2 border-l border-line pl-6">
        {events.map((event) => {
          const summary = eventSummary(event)
          const actor = event.admin_username ?? event.requester_email ?? 'System'
          return (
            <li key={event.id} className="relative pb-5 last:pb-0">
              <span className="absolute -left-[1.82rem] top-4 size-3 rounded-full border-2 border-surface bg-brand-500" aria-hidden="true" />
              <article className="rounded-xl border border-line bg-surface p-4 shadow-sm">
                <div className="flex flex-wrap items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-semibold text-ink">{eventLabel(event)}</h3>
                      {event.booking_reference ? (
                        linkSchedules ? (
                          <a className="badge bg-brand-50 tnum text-brand-700 ring-1 ring-brand-100 hover:bg-brand-100" href={`#/audit/${encodeURIComponent(event.booking_reference)}`}>
                            {event.booking_reference}
                          </a>
                        ) : (
                          <span className="badge bg-canvas tnum text-ink-muted ring-1 ring-line">{event.booking_reference}</span>
                        )
                      ) : (
                        <span className="badge bg-canvas text-ink-muted ring-1 ring-line">System / configuration</span>
                      )}
                    </div>
                    {summary ? <p className="mt-1 text-sm text-ink-muted">{summary}</p> : null}
                  </div>
                  <time className="shrink-0 text-xs tnum text-ink-muted">{formatTimestamp(event.created_at, timezone)}</time>
                </div>

                <p className="mt-2 flex flex-wrap items-center gap-x-2 text-xs text-ink-muted">
                  {event.actor_type === 'ADMIN' ? <Shield className="size-3.5" /> : <User className="size-3.5" />}
                  <span className="font-medium text-ink">{actor}</span>
                  <span>· {titleCase(event.actor_type)}</span>
                </p>

                {event.override_reason ? (
                  <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
                    <strong>Override:</strong> {event.override_reason}
                  </p>
                ) : null}

                <ChangeDetails event={event} />
              </article>
            </li>
          )
        })}
      </ol>
      {more ? (
        <button className="btn-secondary mt-4" disabled={busy} onClick={async () => {
          const beforeId = events[events.length - 1]?.id
          if (!beforeId) return
          setBusy(true)
          try {
            const rows = scoped && bookingId
              ? await api.getBookingAudit(bookingId, beforeId)
              : await api.getAudit({ bookingId, q: query, eventType, actorType: actorType || undefined, beforeId, limit: pageSize })
            setEvents((current) => [...(current ?? []), ...rows])
            setMore(rows.length === pageSize)
          } catch {
            setError('Could not load older history. Please retry.')
          } finally {
            setBusy(false)
          }
        }}>
          {busy ? <Spinner className="size-4" /> : null}
          Load older history
        </button>
      ) : null}
    </>
  )
}
