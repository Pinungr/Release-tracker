import { useState } from 'react'
import { DASHBOARD_HASH } from '../utils/routes'
import type { DateWindowValue, TenantOption } from '../types'
import { AuditHistory } from './AuditHistory'
import { DateWindowFilter, EMPTY_WINDOW } from './DateWindowFilter'
import { History, Search } from './Icons'
import { TenantPicker } from './TenantPicker'

const EVENT_TYPES = [
  ['BOOKING_CREATED', 'Schedule created'],
  ['EMERGENCY_BOOKING_CREATED', 'Emergency schedule created'],
  ['BOOKING_CLONED', 'Schedule cloned'],
  ['BOOKING_EDITED', 'Schedule updated'],
  ['SLOT_CHANGED', 'Schedule moved'],
  ['BOOKING_RESCHEDULED', 'Schedule rescheduled'],
  ['BOOKING_CANCELLED', 'Schedule cancelled'],
  ['BOOKING_DELETED', 'Schedule deleted'],
  ['BOOKING_STATUS_CHANGED', 'Status changed'],
  ['BOOKING_REOPENED', 'Schedule reopened'],
  ['RM_USERS_ASSIGNED', 'Release Manager assigned'],
  ['WORK_STARTED', 'Work started'],
  ['CHANGE_NUMBER_UPDATED', 'Change Number updated'],
  ['DOCUMENT_ADDED', 'Document uploaded'],
  ['DOCUMENT_REPLACED', 'Document replaced'],
  ['DOCUMENT_DELETED', 'Document removed'],
  ['DOCUMENTS_DELETED', 'Selected documents removed'],
  ['COLLABORATOR_ADDED', 'Collaborator added'],
  ['COLLABORATOR_REMOVED', 'Collaborator removed'],
  ['SLOT_MANUALLY_FROZEN', 'Slot frozen'],
  ['SLOT_MANUALLY_UNFROZEN', 'Slot unfrozen'],
  ['AUTOMATIC_LOCK_UNLOCKED', 'Automatic lock unlocked'],
  ['AUTOMATIC_LOCK_RESTORED', 'Automatic lock restored'],
  ['DOCUMENT_TYPE_CREATED', 'Document type created'],
  ['DOCUMENT_TYPE_RENAMED', 'Document type renamed'],
  ['DOCUMENT_TYPE_UPDATED', 'Document type description updated'],
  ['DOCUMENT_TYPE_ENABLED', 'Document type enabled'],
  ['DOCUMENT_TYPE_DISABLED', 'Document type disabled'],
  ['DOCUMENT_TYPES_REORDERED', 'Document types reordered'],
  ['DOCUMENT_TYPE_REQUIREMENT_CHANGED', 'Document requirement changed'],
  ['DOCUMENT_TYPE_FILE_MODE_CHANGED', 'Document file mode changed'],
  ['DOCUMENT_TYPE_DELETED', 'Document type deleted'],
  ['SLOT_CONFIG_UPDATED', 'Slot configuration updated'],
  ['SETTINGS_UPDATED', 'Settings updated'],
  ['HOLIDAY_CREATED', 'Holiday created'],
  ['HOLIDAY_UPDATED', 'Holiday updated'],
  ['HOLIDAY_DELETED', 'Holiday deleted'],
  ['TENANT_CREATED', 'Tenant created'],
  ['USER_STATUS_UPDATED', 'User status updated'],
  ['PASSWORD_RESET_BY_ADMIN', 'Password reset'],
] as const

export function AuditPage({ timezone }: { timezone: string }) {
  const [query, setQuery] = useState('')
  const [eventType, setEventType] = useState('')
  const [actorType, setActorType] = useState<'' | 'USER' | 'ADMIN' | 'SYSTEM'>('')
  const [tenant, setTenant] = useState<TenantOption | null>(null)
  const [dateWindow, setDateWindow] = useState<DateWindowValue>(EMPTY_WINDOW)
  const [applied, setApplied] = useState({
    query: '',
    eventType: '',
    actorType: '' as '' | 'USER' | 'ADMIN' | 'SYSTEM',
    tenant: null as TenantOption | null,
    window: EMPTY_WINDOW,
  })
  const invalidRange = Boolean(dateWindow.dateFrom && dateWindow.dateTo && dateWindow.dateFrom > dateWindow.dateTo)

  function apply() {
    if (invalidRange) return
    setApplied({ query: query.trim(), eventType, actorType, tenant, window: dateWindow })
  }

  function clear() {
    setQuery('')
    setEventType('')
    setActorType('')
    setTenant(null)
    setDateWindow(EMPTY_WINDOW)
    setApplied({ query: '', eventType: '', actorType: '', tenant: null, window: EMPTY_WINDOW })
  }

  return (
    <main className="mx-auto w-full max-w-[88rem] flex-1 space-y-5 px-4 py-6 sm:px-6 lg:px-8">
      <a className="btn-secondary inline-flex" href={DASHBOARD_HASH}>← Back to calendar</a>
      <header className="card p-5 sm:p-6">
        <div className="flex flex-wrap items-start gap-4">
          <div className="grid size-11 place-items-center rounded-xl bg-brand-50 text-brand-700"><History className="size-5" /></div>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-bold uppercase tracking-wide text-ink-muted">Release controls</p>
            <h1 className="mt-1 text-2xl font-bold text-ink">Audit trail</h1>
            <p className="mt-1 max-w-3xl text-sm text-ink-muted">Search the immutable history of schedules and administrative changes. Open any Schedule No. to see that schedule’s focused timeline.</p>
          </div>
        </div>
      </header>

      <section className="card p-5" aria-label="Audit filters">
        <form className="grid gap-3 lg:grid-cols-4 lg:items-end" onSubmit={(event) => { event.preventDefault(); apply() }}>
          <label className="text-xs font-semibold text-ink-muted">Search history
            <div className="relative mt-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-muted" />
              <input className="field pl-9" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Schedule No., user, Change No., value…" maxLength={120} />
            </div>
          </label>
          <label className="text-xs font-semibold text-ink-muted">Action
            <select className="field mt-1" value={eventType} onChange={(event) => setEventType(event.target.value)}>
              <option value="">All actions</option>
              {EVENT_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label className="text-xs font-semibold text-ink-muted">Performed by
            <select className="field mt-1" value={actorType} onChange={(event) => setActorType(event.target.value as typeof actorType)}>
              <option value="">Everyone</option>
              <option value="ADMIN">Owner / Release Manager</option>
              <option value="USER">Tenant user</option>
              <option value="SYSTEM">System</option>
            </select>
          </label>
          <TenantPicker id="audit-tenant" value={tenant} onChange={setTenant} />
          <DateWindowFilter idPrefix="audit" value={dateWindow} onChange={setDateWindow} />
          <div className="flex gap-2">
            <button className="btn-primary" type="submit" disabled={invalidRange}>Apply</button>
            <button className="btn-secondary" type="button" onClick={clear}>Clear filters</button>
          </div>
        </form>
      </section>

      <section className="card p-5 sm:p-6">
        <AuditHistory
          timezone={timezone}
          query={applied.query}
          eventType={applied.eventType}
          actorType={applied.actorType}
          tenantId={applied.tenant?.id ?? null}
          window={applied.window}
          linkSchedules
        />
      </section>
    </main>
  )
}
