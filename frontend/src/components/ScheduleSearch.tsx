import { useRef, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { ScheduleSearchResult, TenantOption, TenantUpcoming } from '../types'
import { BookingStatusBadge } from './StatusBadge'
import { Spinner } from './Icons'
import { TenantPicker } from './TenantPicker'
import { TenantUpcomingResults } from './TenantUpcomingResults'
import { formatDate } from '../utils/dates'

/**
 * Two ways to find schedules without paging the calendar week by week:
 * by tenant (their upcoming schedules, grouped by week) or by Schedule No.
 */
export function ScheduleSearch({ onOpen }: { onOpen: (id: number, bookingReference?: string) => void }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<ScheduleSearchResult[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [searched, setSearched] = useState('')
  const [more, setMore] = useState(false)
  const generation = useRef(0)

  const [tenant, setTenant] = useState<TenantOption | null>(null)
  const [upcoming, setUpcoming] = useState<TenantUpcoming | null>(null)
  const [tenantBusy, setTenantBusy] = useState(false)
  const [tenantError, setTenantError] = useState('')
  const tenantGeneration = useRef(0)

  async function search(older = false) {
    const term = older ? searched : query.trim()
    if (term.length < 2) { setError('Enter at least two characters of the Schedule No.'); return }
    const request = ++generation.current
    setBusy(true); setError('')
    try {
      const rows = await api.searchSchedules(term, older ? results?.[results.length - 1]?.id : undefined)
      if (request !== generation.current) return
      setResults(current => older ? [...(current ?? []), ...rows] : rows)
      setSearched(term); setMore(rows.length === 25)
    } catch (e) { if (request === generation.current) setError(e instanceof ApiError ? e.message : 'Could not search schedules.') }
    finally { if (request === generation.current) setBusy(false) }
  }
  function clear() { ++generation.current; setResults(null); setError(''); setBusy(false) }

  async function selectTenant(next: TenantOption | null) {
    const request = ++tenantGeneration.current
    setTenant(next)
    setUpcoming(null)
    setTenantError('')
    if (!next) { setTenantBusy(false); return }
    setTenantBusy(true)
    try {
      const result = await api.getTenantUpcoming(next.id)
      if (request === tenantGeneration.current) setUpcoming(result)
    } catch (e) {
      if (request === tenantGeneration.current) setTenantError(e instanceof ApiError ? e.message : 'Could not load upcoming schedules.')
    } finally {
      if (request === tenantGeneration.current) setTenantBusy(false)
    }
  }

  function open(id: number, reference?: string) {
    onOpen(id, reference)
    clear()
    void selectTenant(null)
  }

  return <section className="mx-auto w-full max-w-[88rem] px-4 pt-4 sm:px-6 lg:px-8" aria-label="Find a schedule">
    <div className="grid gap-3 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] lg:items-end">
      <TenantPicker id="tenant-search" label="Search a tenant's upcoming schedules" placeholder="e.g. NCAP" value={tenant} onChange={(next) => void selectTenant(next)} />
      <form className="flex flex-wrap items-end gap-2" onSubmit={e => { e.preventDefault(); void search() }}>
        <label className="min-w-48 flex-1 text-xs font-semibold text-ink-muted">Search Schedule No. across all dates
          <input className="field mt-1" value={query} maxLength={100} onChange={e => { setQuery(e.target.value); clear() }} placeholder="e.g. pds-001" />
        </label>
        <button className="btn-primary" disabled={busy || query.trim().length < 2}>{busy ? 'Searching…' : 'Find schedule'}</button>
        {results !== null && <button type="button" className="btn-secondary" onClick={clear}>Close results</button>}
      </form>
    </div>

    {tenant && (tenantBusy || upcoming || tenantError) ? (
      <div className="card mt-3 p-4" aria-live="polite">
        <div className="mb-3 flex items-center justify-end">
          <button type="button" className="btn-secondary btn-sm" onClick={() => void selectTenant(null)}>Close tenant results</button>
        </div>
        {tenantBusy ? <p className="flex items-center gap-2 text-sm text-ink-muted"><Spinner className="size-4" /> Finding {tenant.name}'s upcoming schedules…</p> : null}
        {tenantError ? <p role="alert" className="text-sm text-rose-700">{tenantError}</p> : null}
        {upcoming ? <TenantUpcomingResults result={upcoming} onOpen={open} /> : null}
      </div>
    ) : null}

    {error && <p role="alert" className="mt-2 text-sm text-rose-700">{error}</p>}
    {results !== null && <div className="card mt-3 space-y-2 p-3" aria-live="polite">
      {results.length === 0 && <p className="text-sm text-ink-muted">No accessible schedules match this number. Check the number or your access.</p>}
      {results.map(row => <button key={row.id} className="flex w-full flex-wrap items-center gap-3 rounded-lg border border-line p-3 text-left hover:bg-canvas" onClick={() => open(row.id, row.booking_reference)}>
        <strong className="text-sm text-brand-700">{row.booking_reference}</strong><span className="text-sm">{row.tenant_name}</span><span className="text-xs text-ink-muted">{formatDate(row.deployment_date)}</span><BookingStatusBadge status={row.status} />
      </button>)}
      {more && <button className="btn-secondary" disabled={busy} onClick={() => void search(true)}>Load more results</button>}
    </div>}
  </section>
}
