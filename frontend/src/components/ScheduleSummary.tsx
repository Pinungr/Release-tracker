import type { ScheduleSummary as Summary } from '../types'
import { Calendar, Check, Siren, Sun, User } from './Icons'

interface ScheduleSummaryProps {
  summary: Summary
  myBookingCount: number
  onShowMine: () => void
}

interface CardProps {
  label: string
  value: string
  hint?: string
  icon: React.ReactNode
  tone: string
  onClick?: () => void
}

function Card({ label, value, hint, icon, tone, onClick }: CardProps) {
  const content = (
    <>
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold tracking-wide text-ink-muted uppercase">{label}</p>
        <span className={`grid size-7 shrink-0 place-items-center rounded-md ${tone}`}>{icon}</span>
      </div>
      <p className="mt-2 text-2xl leading-none font-semibold tnum text-ink">{value}</p>
      {hint ? <p className="mt-1 text-xs text-ink-muted">{hint}</p> : null}
    </>
  )

  return onClick ? (
    <button
      type="button"
      onClick={onClick}
      className="card p-4 text-left transition-shadow hover:shadow-raised"
    >
      {content}
    </button>
  ) : (
    <div className="card p-4">{content}</div>
  )
}

export function ScheduleSummary({ summary, myBookingCount, onShowMine }: ScheduleSummaryProps) {
  return (
    <section
      className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5"
      aria-label="Week at a glance"
    >
      <Card
        label="Regular available"
        value={`${summary.regular_slots_available} / ${summary.regular_slots_total}`}
        hint="Sunday to Thursday"
        icon={<Check className="size-4 text-emerald-600" />}
        tone="bg-emerald-50"
      />
      <Card
        label="Slots booked"
        value={String(summary.slots_booked)}
        hint="Regular deployments"
        icon={<Calendar className="size-4 text-brand-600" />}
        tone="bg-brand-50"
      />
      <Card
        label="My changes"
        value={String(myBookingCount)}
        hint={myBookingCount ? 'Click to filter the board' : 'None scheduled by you this week'}
        icon={<User className="size-4 text-teal-600" />}
        tone="bg-teal-50"
        onClick={onShowMine}
      />
      <Card
        label="Holidays"
        value={String(summary.holidays)}
        hint={summary.holidays ? 'Deployments blocked' : 'None this week'}
        icon={<Sun className="size-4 text-amber-600" />}
        tone="bg-amber-50"
      />
      <Card
        label="Emergency CRs"
        value={String(summary.emergency_changes)}
        hint="Owner / Release Manager queue"
        icon={<Siren className="size-4 text-orange-600" />}
        tone="bg-orange-50"
      />
    </section>
  )
}
