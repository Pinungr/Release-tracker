import { useState } from 'react'
import type { FilterKey, TenantOption } from '../types'
import { exactTenant, useTenantSuggestions } from '../hooks/useTenantSuggestions'
import { Cross, Search } from './Icons'

interface ScheduleFiltersProps {
  query: string
  onQueryChange: (value: string) => void
  filter: FilterKey
  onFilterChange: (value: FilterKey) => void
  technologies: string[]
  isAdmin: boolean
  resultCount: number | null
  /** Show one tenant's upcoming schedules instead of the calendar week. */
  onPickTenant?: (tenant: TenantOption) => void
  /** A tenant's upcoming view is showing; week filters do not apply to it. */
  tenantMode?: boolean
}

const BASE_FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'ALL', label: 'All' },
  { key: 'AVAILABLE', label: 'Available' },
  { key: 'BOOKED', label: 'Booked' },
  { key: 'MINE', label: 'My changes' },
]

const ADMIN_FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'EMERGENCY', label: 'Emergency' },
  { key: 'LOCKED', label: 'Locked' },
  { key: 'MISSING_DOCS', label: 'Missing documents' },
]

export function ScheduleFilters({
  query,
  onQueryChange,
  filter,
  onFilterChange,
  technologies,
  isAdmin,
  resultCount,
  onPickTenant,
  tenantMode = false,
}: ScheduleFiltersProps) {
  const [focused, setFocused] = useState(false)
  const suggestions = useTenantSuggestions(query, Boolean(onPickTenant) && !tenantMode)
  const showSuggestions = focused && !tenantMode && suggestions.length > 0

  function pick(tenant: TenantOption) {
    setFocused(false)
    onPickTenant?.(tenant)
  }
  const chips = [
    ...BASE_FILTERS,
    ...technologies.map((tech) => ({ key: `TECH:${tech}` as FilterKey, label: tech })),
    ...(isAdmin ? ADMIN_FILTERS : []),
  ]

  return (
    <section className="card p-3 sm:p-4" aria-label="Search and filter deployments">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <div className="relative lg:w-80">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-muted" />
          <input
            type="search"
            role="combobox"
            aria-expanded={showSuggestions}
            aria-controls="board-search-tenants"
            aria-autocomplete="list"
            autoComplete="off"
            value={query}
            onChange={(event) => { onQueryChange(event.target.value); setFocused(true) }}
            onFocus={() => setFocused(true)}
            onBlur={() => window.setTimeout(() => setFocused(false), 120)}
            onKeyDown={(event) => {
              // Enter on a tenant's exact name opens that tenant's upcoming view.
              const match = event.key === 'Enter' ? exactTenant(suggestions, query) : undefined
              if (match) { event.preventDefault(); pick(match) }
            }}
            placeholder="Search tenant, JIRA, verifier or requester"
            aria-label="Search deployments"
            className="field pl-9"
          />
          {query ? (
            <button
              type="button"
              onClick={() => onQueryChange('')}
              className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-1 text-ink-muted hover:text-ink"
              aria-label="Clear search"
            >
              <Cross className="size-3.5" />
            </button>
          ) : null}
          {showSuggestions ? (
            <ul id="board-search-tenants" role="listbox" className="absolute z-40 mt-1 max-h-64 w-full overflow-y-auto rounded-lg border border-line bg-surface py-1 shadow-lg">
              {suggestions.map((tenant) => (
                <li
                  key={tenant.id}
                  role="option"
                  aria-selected={false}
                  className="cursor-pointer px-3 py-2 text-sm text-ink hover:bg-canvas"
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => pick(tenant)}
                >
                  Show upcoming schedules for <span className="font-semibold">{tenant.name}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>

        {tenantMode ? null : <div className="-mx-1 flex flex-1 flex-wrap gap-1.5 px-1">
          {chips.map((chip) => {
            const active = filter === chip.key
            return (
              <button
                key={chip.key}
                type="button"
                aria-pressed={active}
                onClick={() => onFilterChange(active ? 'ALL' : chip.key)}
                className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors ${
                  active
                    ? 'border-brand-600 bg-brand-600 text-white'
                    : 'border-line bg-surface text-ink-muted hover:border-brand-100 hover:bg-brand-50 hover:text-brand-700'
                }`}
              >
                {chip.label}
              </button>
            )
          })}
        </div>}
      </div>

      {resultCount !== null && !tenantMode ? (
        <p className="mt-3 text-xs text-ink-muted">
          {resultCount === 0
            ? 'No slots match the current search or filter.'
            : `${resultCount} slot${resultCount === 1 ? '' : 's'} match.`}
        </p>
      ) : null}
    </section>
  )
}
