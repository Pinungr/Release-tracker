import type { DateWindowValue } from '../types'

export const DAY_RANGES = [7, 15, 30, 60, 90] as const

export const EMPTY_WINDOW: DateWindowValue = { days: null, dateFrom: '', dateTo: '' }

export function isWindowEmpty(window: DateWindowValue): boolean {
  return window.days === null && !window.dateFrom && !window.dateTo
}

/**
 * Days or a custom From/To range — never both.
 *
 * Choosing a Days range clears the dates, and entering either date clears the
 * Days range, so the filters can never contradict each other and the backend
 * never receives both.
 */
export function DateWindowFilter({
  value,
  onChange,
  idPrefix,
}: {
  value: DateWindowValue
  onChange: (next: DateWindowValue) => void
  idPrefix: string
}) {
  const invalidRange = Boolean(value.dateFrom && value.dateTo && value.dateFrom > value.dateTo)
  return (
    <>
      <label className="text-xs font-semibold text-ink-muted" htmlFor={`${idPrefix}-days`}>
        Days
        <select
          id={`${idPrefix}-days`}
          className="field mt-1"
          value={value.days ?? ''}
          onChange={(event) => onChange(
            event.target.value
              ? { days: Number(event.target.value), dateFrom: '', dateTo: '' }
              : { ...value, days: null },
          )}
        >
          <option value="">Any time</option>
          {DAY_RANGES.map((days) => <option key={days} value={days}>Last {days} days</option>)}
        </select>
      </label>
      <label className="text-xs font-semibold text-ink-muted" htmlFor={`${idPrefix}-from`}>
        From date
        <input
          id={`${idPrefix}-from`}
          type="date"
          className="field mt-1"
          value={value.dateFrom}
          max={value.dateTo || undefined}
          onChange={(event) => onChange({ ...value, days: null, dateFrom: event.target.value })}
        />
      </label>
      <label className="text-xs font-semibold text-ink-muted" htmlFor={`${idPrefix}-to`}>
        To date
        <input
          id={`${idPrefix}-to`}
          type="date"
          className="field mt-1"
          value={value.dateTo}
          min={value.dateFrom || undefined}
          aria-invalid={invalidRange}
          onChange={(event) => onChange({ ...value, days: null, dateTo: event.target.value })}
        />
      </label>
      {invalidRange ? <p role="alert" className="text-xs text-rose-600 lg:col-span-full">From date must be on or before To date.</p> : null}
    </>
  )
}
