/** The dashboard (weekly board) has its own address rather than a bare `#`. */
export const DASHBOARD_HASH = '#/dashboard'

export interface BookSlotTarget {
  date: string
  slotNumber: number
}

/** Link to a specific slot on the weekly board. */
export function bookSlotHash(date: string, slotNumber: number): string {
  return `${DASHBOARD_HASH}?date=${encodeURIComponent(date)}&slot=${slotNumber}`
}

export function parseBookSlotHash(hash: string): BookSlotTarget | null {
  if (!hash.startsWith(`${DASHBOARD_HASH}?`)) return null
  const params = new URLSearchParams(hash.slice(DASHBOARD_HASH.length + 1))
  const date = params.get('date') ?? ''
  const slot = params.get('slot') ?? ''
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !/^[1-9]\d*$/.test(slot)) return null
  const [year, month, day] = date.split('-').map(Number)
  const parsed = new Date(Date.UTC(year, month - 1, day))
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== date) return null
  const slotNumber = Number(slot)
  if (!Number.isSafeInteger(slotNumber)) return null
  return { date, slotNumber }
}

/** Dashboard addresses, including direct links to a slot. */
export function isDashboardHash(hash: string): boolean {
  return hash === '' || hash === '#' || hash === '#/' || hash === DASHBOARD_HASH || parseBookSlotHash(hash) !== null
}

/**
 * Show the dashboard at its proper address without adding a history entry,
 * so Back does not return to the page that was showing before sign-in.
 */
export function replaceWithDashboard(): void {
  if (window.location.hash === DASHBOARD_HASH) return
  const { pathname, search } = window.location
  window.history.replaceState(window.history.state, '', `${pathname}${search}${DASHBOARD_HASH}`)
}
