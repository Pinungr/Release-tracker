import { useRef, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { DateWindowValue, ScheduleListItem, ScheduleSearchResult, TenantOption, TenantUpcoming } from '../types'
import { exactTenant, useTenantSuggestions } from '../hooks/useTenantSuggestions'
import { DateWindowFilter, EMPTY_WINDOW, isWindowEmpty } from './DateWindowFilter'
import { BookingStatusBadge } from './StatusBadge'
import { ScheduleListRow } from './ScheduleListRow'
import { TenantUpcomingResults } from './TenantUpcomingResults'
import { Search, Spinner } from './Icons'
import { formatDate } from '../utils/dates'

const NUMBER_PAGE = 25
const HISTORY_PAGE = 50

type Results =
  | { kind: 'number'; term: string; rows: ScheduleSearchResult[] }
  | { kind: 'upcoming'; tenant: TenantOption; result: TenantUpcoming }
  | { kind: 'history'; tenant: TenantOption | null; term: string; window: DateWindowValue; rows: ScheduleListItem[] }

/**
 * One box for finding schedules across all dates: by Schedule No., or by
 * tenant, optionally narrowed to a recent period or an exact date range.
 *
 * A plain Schedule No. with no dates keeps the original all-dates number
 * search. A tenant with no date filter opens that tenant's upcoming/open
 * schedules. Adding Days or a From/To range switches to server-side history.
 */
export function ScheduleSearch({ onOpen }: { onOpen: (id: number, bookingReference?: string) => void }) {
  const [text, setText] = useState('')
  const [tenant, setTenant] = useState<TenantOption | null>(null)
  const [dateWindow, setDateWindow] = useState<DateWindowValue>(EMPTY_WINDOW)
  const [focused, setFocused] = useState(false)
  const [results, setResults] = useState<Results | null>(null)
  const [more, setMore] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const generation = useRef(0)

  const suggestions = useTenantSuggestions(text, tenant === null)
  const showSuggestions = focused && tenant === null && suggestions.length > 0
  const invalidRange = Boolean(dateWindow.dateFrom && dateWindow.dateTo && dateWindow.dateFrom > dateWindow.dateTo)
  const canSearch = !invalidRange && (tenant !== null || !isWindowEmpty(dateWindow) || text.trim().length >= 2)
  const dirty = Boolean(text || tenant || !isWindowEmpty(dateWindow) || results)

  function pickTenant(next: TenantOption) {
    setTenant(next)
    setText(next.name)
    setFocused(false)
  }

  async function search() {
    // Typing a tenant's exact name counts as choosing it.
    const chosen = tenant ?? exactTenant(suggestions, text) ?? null
    if (chosen && !tenant) pickTenant(chosen)
    const term = text.trim()
    const request = ++generation.current
    setBusy(true); setError('')
    try {
      if (chosen && isWindowEmpty(dateWindow)) {
        const result = await api.getTenantUpcoming(chosen.id)
        if (request !== generation.current) return
        setResults({ kind: 'upcoming', tenant: chosen, result })
        setMore(false)
      } else if (!chosen && isWindowEmpty(dateWindow)) {
        if (term.length < 2) { setError('Enter at least two characters, choose a tenant, or pick a date range.'); return }
        const rows = await api.searchSchedules(term)
        if (request !== generation.current) return
        setResults({ kind: 'number', term, rows })
        setMore(rows.length === NUMBER_PAGE)
      } else {
        const rows = await api.getScheduleHistory({
          tenantId: chosen?.id,
          q: chosen ? undefined : term || undefined,
          window: dateWindow,
          limit: HISTORY_PAGE,
        })
        if (request !== generation.current) return
        setResults({ kind: 'history', tenant: chosen, term: chosen ? '' : term, window: dateWindow, rows })
        setMore(rows.length === HISTORY_PAGE)
      }
    } catch (e) {
      if (request === generation.current) setError(e instanceof ApiError ? e.message : 'Could not search schedules.')
    } finally {
      if (request === generation.current) setBusy(false)
    }
  }

  async function loadMore() {
    if (!results || results.kind === 'upcoming') return
    const request = generation.current
    setBusy(true)
    try {
      if (results.kind === 'number') {
        const rows = await api.searchSchedules(results.term, results.rows[results.rows.length - 1]?.id)
        if (request !== generation.current) return
        setResults({ ...results, rows: [...results.rows, ...rows] })
        setMore(rows.length === NUMBER_PAGE)
      } else {
        const last = results.rows[results.rows.length - 1]
        const rows = await api.getScheduleHistory({
          tenantId: results.tenant?.id,
          q: results.term || undefined,
          window: results.window,
          before: last ? { date: last.deployment_date, id: last.id } : undefined,
          limit: HISTORY_PAGE,
        })
        if (request !== generation.current) return
        setResults({ ...results, rows: [...results.rows, ...rows] })
        setMore(rows.length === HISTORY_PAGE)
      }
    } catch {
      setError('Could not load more results. Please retry.')
    } finally {
      setBusy(false)
    }
  }

  function clear() {
    ++generation.current
    setText(''); setTenant(null); setDateWindow(EMPTY_WINDOW)
    setResults(null); setMore(false); setError(''); setBusy(false)
  }

  function open(id: number, reference?: string) {
    onOpen(id, reference)
    clear()
  }

  return <section className="mx-auto w-full max-w-[88rem] px-4 pt-4 sm:px-6 lg:px-8" aria-label="Find a schedule">
    <form className="grid gap-3 lg:grid-cols-[minmax(16rem,1fr)_10rem_10rem_10rem_auto] lg:items-end" onSubmit={e => { e.preventDefault(); if (canSearch) void search() }}>
      <div className="relative text-xs font-semibold text-ink-muted">
        <label htmlFor="schedule-search">Search Schedule No. or tenant across all dates</label>
        <div className="relative mt-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-muted" />
          <input
            id="schedule-search"
            role="combobox"
            aria-expanded={showSuggestions}
            aria-controls="schedule-search-tenants"
            aria-autocomplete="list"
            autoComplete="off"
            className="field pl-9"
            value={text}
            maxLength={100}
            placeholder="e.g. pds-001 or NCAP"
            onFocus={() => setFocused(true)}
            onBlur={() => window.setTimeout(() => setFocused(false), 120)}
            onChange={e => {
              setText(e.target.value)
              setFocused(true)
              // Editing the text drops a previously chosen tenant.
              if (tenant) setTenant(null)
            }}
          />
        </div>
        {tenant ? <p className="mt-1 font-normal text-brand-700">Tenant: {tenant.name}</p> : null}
        {showSuggestions ? (
          <ul id="schedule-search-tenants" role="listbox" className="absolute z-40 mt-1 max-h-64 w-full overflow-y-auto rounded-lg border border-line bg-surface py-1 shadow-lg">
            {suggestions.map(option => (
              <li key={option.id} role="option" aria-selected={false}
                className="cursor-pointer px-3 py-2 text-sm font-normal text-ink hover:bg-canvas"
                onMouseDown={e => e.preventDefault()}
                onClick={() => pickTenant(option)}>
                Tenant: <span className="font-semibold">{option.name}</span>
                {!option.is_active ? <span className="ml-2 text-xs text-ink-muted">inactive</span> : null}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      <DateWindowFilter idPrefix="schedule-search" value={dateWindow} onChange={setDateWindow} />
      <div className="flex gap-2">
        <button className="btn-primary" disabled={busy || !canSearch}>{busy ? 'Searching…' : 'Find schedule'}</button>
        {dirty ? <button type="button" className="btn-secondary" onClick={clear}>Clear filters</button> : null}
      </div>
    </form>

    {error && <p role="alert" className="mt-2 text-sm text-rose-700">{error}</p>}

    {results?.kind === 'number' && <div className="card mt-3 space-y-2 p-3" aria-live="polite">
      {results.rows.length === 0 && <p className="text-sm text-ink-muted">No accessible schedules match this number. Check the number or your access.</p>}
      {results.rows.map(row => <button key={row.id} className="flex w-full flex-wrap items-center gap-3 rounded-lg border border-line p-3 text-left hover:bg-canvas" onClick={() => open(row.id, row.booking_reference)}>
        <strong className="text-sm text-brand-700">{row.booking_reference}</strong><span className="text-sm">{row.tenant_name}</span><span className="text-xs text-ink-muted">{formatDate(row.deployment_date)}</span><BookingStatusBadge status={row.status} />
      </button>)}
      {more && <button className="btn-secondary" disabled={busy} onClick={() => void loadMore()}>Load more results</button>}
    </div>}

    {results?.kind === 'upcoming' && <div className="card mt-3 p-3" aria-live="polite">
      <TenantUpcomingResults result={results.result} onOpen={open} />
    </div>}

    {results?.kind === 'history' && <div className="card mt-3 space-y-2 p-3" aria-live="polite">
      <p className="text-xs font-semibold text-ink-muted">{describe(results)}</p>
      {results.rows.length === 0 && <p className="text-sm text-ink-muted">No schedules match these filters.</p>}
      {results.rows.map(row => <ScheduleListRow key={row.id} schedule={row} onOpen={open} showTenant={results.tenant === null} />)}
      {more && <button className="btn-secondary" disabled={busy} onClick={() => void loadMore()}>{busy ? <Spinner className="size-4" /> : null}Load older schedules</button>}
    </div>}
  </section>
}

function describe(results: Extract<Results, { kind: 'history' }>): string {
  const who = results.tenant ? results.tenant.name : results.term ? `Schedule No. containing “${results.term}”` : 'All tenants'
  const { days, dateFrom, dateTo } = results.window
  const when = days
    ? `last ${days} days`
    : dateFrom || dateTo
      ? `${dateFrom ? formatDate(dateFrom) : 'the beginning'} – ${dateTo ? formatDate(dateTo) : 'any date'}`
      : results.tenant ? 'past schedules' : 'all dates'
  return `${who} · ${when} · newest first`
}
