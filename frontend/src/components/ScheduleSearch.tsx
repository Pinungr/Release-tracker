import { useRef, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { ScheduleSearchResult } from '../types'
import { BookingStatusBadge } from './StatusBadge'
import { formatDate } from '../utils/dates'

export function ScheduleSearch({ onOpen }: { onOpen: (id: number) => void }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<ScheduleSearchResult[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [searched, setSearched] = useState('')
  const [more, setMore] = useState(false)
  const generation = useRef(0)
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
  return <section className="mx-auto w-full max-w-[88rem] px-4 pt-4 sm:px-6 lg:px-8" aria-label="Find a schedule">
    <form className="flex flex-wrap items-end gap-2" onSubmit={e => { e.preventDefault(); void search() }}>
      <label className="min-w-48 flex-1 text-xs font-semibold text-ink-muted">Search Schedule No. across all dates
        <input className="field mt-1" value={query} maxLength={100} onChange={e => { setQuery(e.target.value); clear() }} placeholder="e.g. pds-001" />
      </label>
      <button className="btn-primary" disabled={busy || query.trim().length < 2}>{busy ? 'Searching…' : 'Find schedule'}</button>
      {results !== null && <button type="button" className="btn-secondary" onClick={clear}>Close results</button>}
    </form>
    {error && <p role="alert" className="mt-2 text-sm text-rose-700">{error}</p>}
    {results !== null && <div className="card mt-3 space-y-2 p-3" aria-live="polite">
      {results.length === 0 && <p className="text-sm text-ink-muted">No accessible schedules match this number. Check the number or your access.</p>}
      {results.map(row => <button key={row.id} className="flex w-full flex-wrap items-center gap-3 rounded-lg border border-line p-3 text-left hover:bg-canvas" onClick={() => { onOpen(row.id); clear() }}>
        <strong className="text-sm text-brand-700">{row.booking_reference}</strong><span className="text-sm">{row.tenant_name}</span><span className="text-xs text-ink-muted">{formatDate(row.deployment_date)}</span><BookingStatusBadge status={row.status} />
      </button>)}
      {more && <button className="btn-secondary" disabled={busy} onClick={() => void search(true)}>Load more results</button>}
    </div>}
  </section>
}
