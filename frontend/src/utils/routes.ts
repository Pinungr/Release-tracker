/** The dashboard (weekly board) has its own address rather than a bare `#`. */
export const DASHBOARD_HASH = '#/dashboard'

/** Empty and legacy spellings of the dashboard address. */
export function isDashboardHash(hash: string): boolean {
  return hash === '' || hash === '#' || hash === '#/' || hash === DASHBOARD_HASH
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
