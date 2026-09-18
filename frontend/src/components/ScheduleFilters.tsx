import type { FilterKey } from '../types'
import { Cross, Search } from './Icons'

interface ScheduleFiltersProps {
  query: string
  onQueryChange: (value: string) => void
  filter: FilterKey
  onFilterChange: (value: FilterKey) => void
  technologies: string[]
  isAdmin: boolean
  resultCount: number | null
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
}: ScheduleFiltersProps) {
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
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
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
        </div>

        <div className="-mx-1 flex flex-1 flex-wrap gap-1.5 px-1">
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
        </div>
      </div>

      {resultCount !== null ? (
        <p className="mt-3 text-xs text-ink-muted">
          {resultCount === 0
            ? 'No slots match the current search or filter.'
            : `${resultCount} slot${resultCount === 1 ? '' : 's'} match.`}
        </p>
      ) : null}
    </section>
  )
}
