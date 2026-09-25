import { Calendar, ChevronLeft, ChevronRight } from './Icons'

interface WeekNavigatorProps {
  label: string
  onPrevious: () => void
  onNext: () => void
  onToday: () => void
  isCurrentWeek: boolean
  loading: boolean
}

export function WeekNavigator({
  label,
  onPrevious,
  onNext,
  onToday,
  isCurrentWeek,
  loading,
}: WeekNavigatorProps) {
  return (
    <div className="flex items-center gap-1.5">
      <button
        type="button"
        onClick={onPrevious}
        className="btn-secondary px-2.5"
        disabled={loading}
        aria-label="Previous week"
      >
        <ChevronLeft className="size-4" />
        <span className="hidden lg:inline">Previous week</span>
      </button>

      <div className="flex min-w-[13rem] items-center justify-center gap-2 rounded-lg bg-canvas px-3 py-2">
        <Calendar className="size-4 shrink-0 text-ink-muted" />
        <span
          className={`text-sm font-semibold tnum transition-opacity ${loading ? 'opacity-50' : ''}`}
        >
          {label}
        </span>
      </div>

      <button type="button" onClick={onNext} className="btn-secondary px-2.5" disabled={loading} aria-label="Next week">
        <span className="hidden lg:inline">Next week</span>
        <ChevronRight className="size-4" />
      </button>

      <button
        type="button"
        onClick={onToday}
        className="btn-ghost"
        disabled={loading || isCurrentWeek}
        title={isCurrentWeek ? 'Already showing this week' : 'Jump to the current week'}
      >
        Today
      </button>
    </div>
  )
}
