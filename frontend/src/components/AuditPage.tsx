import { useState } from 'react'
import { AuditHistory } from './AuditHistory'
import { History, Search } from './Icons'

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
  ['RM_USERS_ASSIGNED', 'Release Manager assigned'],
  ['WORK_STARTED', 'Work started'],
  ['CHANGE_NUMBER_UPDATED', 'Change Number updated'],
  ['DOCUMENT_ADDED', 'Document uploaded'],
  ['DOCUMENT_DELETED', 'Document removed'],
  ['SLOT_MANUALLY_FROZEN', 'Slot frozen'],
  ['SLOT_MANUALLY_UNFROZEN', 'Slot unfrozen'],
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
  const [applied, setApplied] = useState({ query: '', eventType: '', actorType: '' as '' | 'USER' | 'ADMIN' | 'SYSTEM' })

  function apply() {
    setApplied({ query: query.trim(), eventType, actorType })
  }

  function clear() {
    setQuery('')
    setEventType('')
    setActorType('')
    setApplied({ query: '', eventType: '', actorType: '' })
  }

  return (
    <main className="mx-auto w-full max-w-[88rem] flex-1 space-y-5 px-4 py-6 sm:px-6 lg:px-8">
      <a className="btn-secondary inline-flex" href="#">← Back to calendar</a>
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
        <form className="grid gap-3 lg:grid-cols-[minmax(15rem,1fr)_15rem_12rem_auto] lg:items-end" onSubmit={(event) => { event.preventDefault(); apply() }}>
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
          <div className="flex gap-2">
            <button className="btn-primary" type="submit">Apply</button>
            {(applied.query || applied.eventType || applied.actorType) ? <button className="btn-secondary" type="button" onClick={clear}>Clear</button> : null}
          </div>
        </form>
      </section>

      <section className="card p-5 sm:p-6">
        <AuditHistory timezone={timezone} query={applied.query} eventType={applied.eventType} actorType={applied.actorType} linkSchedules />
      </section>
    </main>
  )
}
