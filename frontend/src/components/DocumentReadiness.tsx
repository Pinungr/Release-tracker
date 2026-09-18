import type { DocumentReadiness as Readiness } from '../types'
import { Alert, Check, Cross } from './Icons'

function toneFor(readiness: Readiness) {
  if (readiness.complete) return 'text-emerald-700'
  if (readiness.provided_required === 0) return 'text-rose-600'
  return 'text-amber-700'
}

/** Compact "4 / 5 documents" pill shown on each booked slot row. */
export function DocumentReadinessPill({ readiness }: { readiness: Readiness }) {
  // Counts the *required* categories, matching the readiness percentage.
  const total = readiness.total_required
  const provided = readiness.provided_required
  return (
    <span className="tooltip-host inline-flex items-center gap-1.5 text-xs font-medium">
      <span className={`inline-flex items-center gap-1 ${toneFor(readiness)}`}>
        {readiness.complete ? <Check className="size-3.5" /> : <Alert className="size-3.5" />}
        <span className="tnum">
          {provided}/{total}
        </span>
        <span className="hidden sm:inline">docs</span>
      </span>
      <span className="tooltip">
        {readiness.complete
          ? 'All required documents attached'
          : `Missing: ${readiness.missing_labels.join(', ')}`}
      </span>
    </span>
  )
}

/** Full checklist shown in the booking details drawer. */
export function DocumentReadinessPanel({ readiness }: { readiness: Readiness }) {
  return (
    <section>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-semibold text-ink">Deployment documentation</h3>
        <span className={`text-sm font-semibold tnum ${toneFor(readiness)}`}>
          {readiness.provided_required} / {readiness.total_required} required ({readiness.percent}%)
        </span>
      </div>

      <div
        className="mb-4 h-1.5 w-full overflow-hidden rounded-full bg-line"
        role="progressbar"
        aria-valuenow={readiness.percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Required document completion"
      >
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            readiness.complete ? 'bg-emerald-500' : 'bg-amber-500'
          }`}
          style={{ width: `${readiness.percent}%` }}
        />
      </div>

      <ul className="space-y-1.5">
        {readiness.items.map((item) => (
          <li key={item.category} className="flex items-center gap-2.5 text-sm">
            {item.provided ? (
              <Check className="size-4 shrink-0 text-emerald-600" />
            ) : item.required ? (
              <Cross className="size-4 shrink-0 text-rose-500" />
            ) : (
              <span className="size-4 shrink-0 text-center text-ink-muted/50">–</span>
            )}
            <span className={item.provided ? 'text-ink' : 'text-ink-muted'}>{item.label}</span>
            {item.required ? (
              <span className="text-[11px] font-semibold tracking-wide text-ink-muted/70 uppercase">
                required
              </span>
            ) : null}
            {item.file_count > 1 ? (
              <span className="text-xs text-ink-muted">({item.file_count} files)</span>
            ) : null}
          </li>
        ))}
      </ul>

      {!readiness.complete ? (
        <p className="mt-3 flex items-start gap-2 rounded-lg bg-amber-50 p-2.5 text-xs text-amber-900">
          <Alert className="mt-0.5 size-4 shrink-0" />
          <span>{readiness.missing_labels.join(', ')} missing.</span>
        </p>
      ) : null}
    </section>
  )
}
