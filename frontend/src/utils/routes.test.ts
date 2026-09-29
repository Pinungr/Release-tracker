import { afterEach, expect, it } from 'vitest'
import { DASHBOARD_HASH, isDashboardHash, replaceWithDashboard } from './routes'

afterEach(() => window.history.replaceState(null, '', '/'))

it('treats the empty and legacy addresses as the dashboard', () => {
  for (const hash of ['', '#', '#/', '#/dashboard']) expect(isDashboardHash(hash)).toBe(true)
  for (const hash of ['#/audit', '#/schedules/pds-001', '#/admin/groups', '#change/4']) {
    expect(isDashboardHash(hash)).toBe(false)
  }
})

it('moves a stale deep link to the dashboard without a new history entry', () => {
  window.history.replaceState(null, '', '/#/schedules/pds-001')
  const entries = window.history.length
  replaceWithDashboard()
  expect(window.location.hash).toBe(DASHBOARD_HASH)
  // Replaced, not pushed: Back will not return to the pre-sign-in page.
  expect(window.history.length).toBe(entries)
})

it('keeps the path and query string', () => {
  window.history.replaceState(null, '', '/app?x=1#/audit')
  replaceWithDashboard()
  expect(window.location.pathname + window.location.search + window.location.hash).toBe('/app?x=1#/dashboard')
})
