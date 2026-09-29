import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { DateWindowValue, ScheduleListItem, TenantOption } from '../types'
import { DateWindowFilter, EMPTY_WINDOW, isWindowEmpty } from './DateWindowFilter'
import { History, Spinner } from './Icons'
import { ScheduleListRow } from './ScheduleListRow'
import { TenantPicker } from './TenantPicker'

const PAGE_SIZE = 50

interface Filters {
  tenant: TenantOption | null
  window: DateWindowValue
}

const DEFAULT_FILTERS: Filters = { tenant: null, window: EMPTY_WINDOW }

/**
 * Schedule history, filtered like a bank statement: Tenant, Days and a
 * From/To range combine freely. Filtering and paging happen on the server;
 * without a date filter it lists past schedules, newest first.
 */
export function HistoryPage({ onOpen }: { onOpen: (id: number, bookingReference?: string) => void }) {
  const [draft, setDraft] = useState<Filters>(DEFAULT_FILTERS)
  const [applied, setApplied] = useState<Filters>(DEFAULT_FILTERS)
  const [rows, setRows] = useState<ScheduleListItem[] | null>(null)
  const [more, setMore] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const generation = useRef(0)

  const invalidRange = Boolean(draft.window.dateFrom && draft.window.dateTo && draft.window.dateFrom > draft.window.dateTo)
  const filtered = applied.tenant !== null || !isWindowEmpty(applied.window)

  useEffect(() => {
    const request = ++generation.current
    setRows(null)
    setError(null)
    api.getScheduleHistory({ tenantId: applied.tenant?.id, window: applied.window, limit: PAGE_SIZE })
      .then((page) => {
        if (request !== generation.current) return
        setRows(page)
        setMore(page.length === PAGE_SIZE)
      })
      .catch((caught) => {
        if (request === generation.current) setError(caught instanceof ApiError ? caught.message : 'Could not load history.')
      })
  }, [applied])

  async function loadMore() {
    const last = rows?.[rows.length - 1]
    if (!last) return
    const request = generation.current
    setBusy(true)
    try {
      const page = await api.getScheduleHistory({
        tenantId: applied.tenant?.id,
        window: applied.window,
        before: { date: last.deployment_date, id: last.id },
        limit: PAGE_SIZE,
      })
      if (request !== generation.current) return
      setRows((current) => [...(current ?? []), ...page])
      setMore(page.length === PAGE_SIZE)
    } catch {
      setError('Could not load older schedules. Please retry.')
    } finally {
      setBusy(false)
    }
  }

  function reset() {
    setDraft(DEFAULT_FILTERS)
    setApplied(DEFAULT_FILTERS)
  }

  return (
    <main className="mx-auto w-full max-w-[88rem] flex-1 space-y-5 px-4 py-6 sm:px-6 lg:px-8">
      <a className="btn-secondary inline-flex" href="#">← Back to calendar</a>
      <header className="card p-5 sm:p-6">
        <div className="flex flex-wrap items-start gap-4">
          <div className="grid size-11 place-items-center rounded-xl bg-brand-50 text-brand-700"><History className="size-5" /></div>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-bold text-ink">Schedule history</h1>
            <p className="mt-1 max-w-3xl text-sm text-ink-muted">
              Past PDS schedules of every status, newest first. Filter by tenant, a recent period or an exact date range.
            </p>
          </div>
        </div>
      </header>

      <section className="card p-5" aria-label="History filters">
        <form
          className="grid gap-3 lg:grid-cols-[minmax(14rem,1fr)_11rem_11rem_11rem_auto] lg:items-end"
          onSubmit={(event) => { event.preventDefault(); if (!invalidRange) setApplied(draft) }}
        >
          <TenantPicker id="history-tenant" value={draft.tenant} onChange={(tenant) => setDraft((d) => ({ ...d, tenant }))} />
          <DateWindowFilter idPrefix="history" value={draft.window} onChange={(window) => setDraft((d) => ({ ...d, window }))} />
          <div className="flex gap-2">
            <button className="btn-primary" type="submit" disabled={invalidRange}>Apply</button>
            <button className="btn-secondary" type="button" onClick={reset}>Clear filters</button>
          </div>
        </form>
      </section>

      <section className="card space-y-2 p-5 sm:p-6" aria-live="polite">
        {error ? <p role="alert" className="text-sm text-rose-600">{error}</p> : null}
        {!rows && !error ? (
          <p className="flex items-center gap-2 py-6 text-sm text-ink-muted"><Spinner className="size-4" /> Loading history…</p>
        ) : null}
        {rows && rows.length === 0 ? (
          <p className="py-6 text-center text-sm text-ink-muted">
            {filtered ? 'No schedules match these filters.' : 'No past schedules yet.'}
          </p>
        ) : null}
        {rows?.map((schedule) => (
          <ScheduleListRow key={schedule.id} schedule={schedule} onOpen={onOpen} showTenant={!applied.tenant} />
        ))}
        {more ? (
          <button className="btn-secondary mt-2" disabled={busy} onClick={() => void loadMore()}>
            {busy ? <Spinner className="size-4" /> : null}
            Load older schedules
          </button>
        ) : null}
      </section>
    </main>
  )
}
