import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { BookingDrawer } from './BookingDrawer'
import { ToastProvider } from './ToastNotification'
import type { DayView, PublicSettings, SlotView } from '../types'
import { api } from '../services/api'

vi.mock('../services/api', () => ({
  api: {
    getActiveTenants: vi.fn().mockResolvedValue([
      { id: 1, name: 'EPCAT', tenant_code: 'EPCAT' },
      { id: 2, name: 'Encounters', tenant_code: 'ENC' },
    ]),
    createBooking: vi.fn(),
  },
  ApiError: class extends Error {},
}))

afterEach(cleanup)

const settings = {
  jira_required_at_booking: false,
  max_file_size_mb: 20,
  technologies: ['Application'],
  document_catalog: [],
} as PublicSettings

const target = {
  day: { day: '2026-10-04', weekday: 'Sunday', date_label: '4 October' } as DayView,
  slot: { slot_number: 1, name: 'Slot 1', time_label: '9 PM–5 AM' } as SlotView,
  isEmergency: false,
}

it('shows Member Pool tenants but requires an explicit tenant selection', async () => {
  render(
    <ToastProvider>
      <BookingDrawer
        open
        onClose={vi.fn()}
        settings={settings}
        isAdmin={false}
        isMemberPool
        createTarget={target}
        editBooking={null}
        onSaved={vi.fn()}
      />
    </ToastProvider>,
  )

  await waitFor(() => expect(api.getActiveTenants).toHaveBeenCalled())
  const tenantSelect = screen.getByLabelText('Tenant name') as HTMLSelectElement
  expect(tenantSelect.value).toBe('')
  expect(screen.getByRole('option', { name: 'EPCAT' })).toBeTruthy()
  expect(screen.getByRole('option', { name: 'Encounters' })).toBeTruthy()

  fireEvent.change(tenantSelect, { target: { value: '2' } })
  expect(tenantSelect.value).toBe('2')
})
