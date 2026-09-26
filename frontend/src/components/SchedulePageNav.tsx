export function SchedulePageNav({ reference, active }: { reference: string; active: 'overview' | 'audit' }) {
  const scheduleUrl = `#/schedules/${encodeURIComponent(reference)}`
  const auditUrl = `#/audit/${encodeURIComponent(reference)}`
  const itemClass = (selected: boolean) => `rounded-lg px-3 py-2 text-sm font-semibold transition-colors ${selected ? 'bg-brand-600 text-white' : 'text-ink-muted hover:bg-canvas hover:text-ink'}`
  return (
    <nav className="flex flex-wrap gap-1" aria-label="Schedule sections">
      <a className={itemClass(active === 'overview')} aria-current={active === 'overview' ? 'page' : undefined} href={scheduleUrl}>Overview</a>
      <a className={itemClass(active === 'audit')} aria-current={active === 'audit' ? 'page' : undefined} href={auditUrl}>Audit</a>
    </nav>
  )
}
