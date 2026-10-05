import { afterEach, expect, it } from 'vitest'
import { bookSlotHash, DASHBOARD_HASH, isDashboardHash, parseBookSlotHash, replaceWithDashboard } from './routes'

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

it('preserves a valid slot booking link to the dashboard', () => {
  const hash = bookSlotHash('2026-10-06', 2)
  expect(hash).toBe('#/dashboard?date=2026-10-06&slot=2')
  expect(isDashboardHash(hash)).toBe(true)
  expect(parseBookSlotHash(hash)).toEqual({ date: '2026-10-06', slotNumber: 2 })
  expect(parseBookSlotHash('#/dashboard?date=2026-02-30&slot=2')).toBeNull()
  expect(parseBookSlotHash('#/dashboard?date=2026-10-06&slot=0')).toBeNull()
})
