import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import type { AuthUser, Schedule } from './types'
import { api } from './services/api'
import App from './App'
import { ToastProvider } from './components/ToastNotification'
import { bookSlotHash, DASHBOARD_HASH } from './utils/routes'

// Unlisted API calls resolve to an empty list.
vi.mock('./services/api', () => {
  const calls: Record<string, ReturnType<typeof vi.fn>> = {}
  return {
    api: new Proxy(calls, { get: (target, key: string) => (target[key] ??= vi.fn().mockResolvedValue([])) }),
    userToken: { get: () => 'token', set: vi.fn(), clear: vi.fn() },
    ApiError: class extends Error {},
  }
})

const DATE = '2026-10-06'

// jsdom has no scrolling; the board scrolls the linked slot into view.
Element.prototype.scrollIntoView = vi.fn()

const tenantUser: AuthUser = {
  id: 5, full_name: 'Tenant User', username: 'tenant', email: 'tenant@example.com', role: 'TENANT_USER',
  groups: [{ id: 3, name: 'EPCAT', group_type: 'TENANT_SUBGROUP', tenant_id: 1 }],
}

function schedule(): Schedule {
  return {
    week_start: '2026-10-04', week_end: '2026-10-08', week_label: '4 - 8 Oct 2026', today: '2026-10-01', timezone: 'Asia/Kolkata',
    summary: { regular_slots_total: 1, regular_slots_available: 1, slots_booked: 0, holidays: 0, emergency_changes: 0 },
    settings: { weekly_booking_limit: 2, booking_freeze_dates: 2, jira_required_at_booking: false, max_file_size_mb: 20, document_catalog: [], technologies: ['Application'] },
    days: [{
      day: DATE, weekday: 'Tuesday', date_label: '6 Oct', is_today: false, is_past: false, holiday: null, custom_slot_count: null,
      regular_slots_total: 1, regular_slots_used: 0, emergency_open: false, emergency_closed_reason: null, emergency_bookings: [],
      slots: [{
        slot_number: 2, name: 'Slot 2', start_time: '21:00', end_time: '05:00', time_label: '9:00 PM - 5:00 AM', enabled: true,
        unavailable_reason: null, state: 'AVAILABLE', bookable: true, manually_frozen: false, booking: null,
      }],
    }],
  } as Schedule
}

function renderApp() {
  vi.mocked(api.me).mockResolvedValue(tenantUser)
  vi.mocked(api.getSchedule).mockResolvedValue(schedule())
  return render(<ToastProvider><App /></ToastProvider>)
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  window.history.replaceState(null, '', '/')
})

it('opens the booking form once and then clears the slot from the address', async () => {
  window.history.replaceState(null, '', `/${bookSlotHash(DATE, 2)}`)
  renderApp()

  expect(await screen.findByText('Book production deployment')).toBeTruthy()
  // The link is consumed in place, so a reload, Back or a bookmark sees the plain board.
  expect(window.location.hash).toBe(DASHBOARD_HASH)
  expect(document.getElementById(`deployment-slot-${DATE}-2`)?.className).toContain('ring-2')
})

it('does not reopen the booking form when the page is reloaded afterwards', async () => {
  window.history.replaceState(null, '', `/${bookSlotHash(DATE, 2)}`)
  const first = renderApp()
  await screen.findByText('Book production deployment')
  first.unmount()

  // "Reload": mount again on whatever address the browser now shows.
  renderApp()
  await waitFor(() => expect(document.getElementById(`deployment-slot-${DATE}-2`)).not.toBeNull())
  expect(screen.queryByText('Book production deployment')).toBeNull()
  expect(screen.queryByText('Slot no longer available')).toBeNull()
  expect(window.location.hash).toBe(DASHBOARD_HASH)
})
