import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import type { DateWindowValue, TenantOption, TenantUpcoming } from '../types'
import { DateWindowFilter, EMPTY_WINDOW } from './DateWindowFilter'
import { TenantPicker } from './TenantPicker'
import { TenantUpcomingResults } from './TenantUpcomingResults'
import { api } from '../services/api'

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      lookupTenants: vi.fn().mockResolvedValue([{ id: 7, name: 'NCAP', tenant_code: 'NCAP', is_active: true }]),
    },
  }
})

afterEach(() => { cleanup(); vi.restoreAllMocks() })

function WindowHarness({ onValue }: { onValue: (value: DateWindowValue) => void }) {
  const [value, setValue] = useState<DateWindowValue>(EMPTY_WINDOW)
  return <DateWindowFilter idPrefix="t" value={value} onChange={(next) => { setValue(next); onValue(next) }} />
}

it('choosing a Days range clears a custom date range', () => {
  const seen: DateWindowValue[] = []
  render(<WindowHarness onValue={(v) => seen.push(v)} />)
  fireEvent.change(screen.getByLabelText('From date'), { target: { value: '2026-09-01' } })
  fireEvent.change(screen.getByLabelText('Days'), { target: { value: '30' } })
  expect(seen.at(-1)).toEqual({ days: 30, dateFrom: '', dateTo: '' })
})

it('entering a date clears the Days range', () => {
  const seen: DateWindowValue[] = []
  render(<WindowHarness onValue={(v) => seen.push(v)} />)
  fireEvent.change(screen.getByLabelText('Days'), { target: { value: '7' } })
  fireEvent.change(screen.getByLabelText('To date'), { target: { value: '2026-09-30' } })
  expect(seen.at(-1)).toEqual({ days: null, dateFrom: '', dateTo: '2026-09-30' })
})

it('flags a From date after the To date', () => {
  render(<DateWindowFilter idPrefix="t" value={{ days: null, dateFrom: '2026-09-30', dateTo: '2026-09-01' }} onChange={() => {}} />)
  expect(screen.getByRole('alert').textContent).toContain('on or before')
})

it('never sends Days and a date range together', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response('[]', { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  await api.getScheduleHistory({ tenantId: 7, window: { days: 30, dateFrom: '2026-09-01', dateTo: '2026-09-30' } })
  const url = String(fetchMock.mock.calls[0][0])
  expect(url).toContain('tenant_id=7')
  expect(url).toContain('date_from=2026-09-01')
  expect(url).toContain('date_to=2026-09-30')
  expect(url).not.toContain('days=')
  vi.unstubAllGlobals()
})

it('suggests a tenant from a partial name and yields its id', async () => {
  const chosen: (TenantOption | null)[] = []
  function Harness() {
    const [value, setValue] = useState<TenantOption | null>(null)
    return <TenantPicker value={value} onChange={(t) => { setValue(t); chosen.push(t) }} />
  }
  render(<Harness />)
  const input = screen.getByRole('combobox')
  fireEvent.focus(input)
  fireEvent.change(input, { target: { value: 'NCA' } })
  await waitFor(() => expect(api.lookupTenants).toHaveBeenCalledWith('NCA'))
  fireEvent.click(await screen.findByRole('option', { name: /NCAP/ }))
  expect(chosen.at(-1)).toEqual({ id: 7, name: 'NCAP', tenant_code: 'NCAP', is_active: true })
})

const schedule = (id: number, ref: string, date: string) => ({
  id, booking_reference: ref, tenant_id: 7, tenant_name: 'NCAP', deployment_date: date,
  slot_number: 1, is_emergency: false, status: 'BOOKED' as const, change_number: null,
  jira_number: 'JIRA-1', jira_url: null, release_managers: ['Asha RM'],
})

it('renders only the weeks the server returned, and opens a schedule', () => {
  const result: TenantUpcoming = {
    tenant_id: 7, tenant_name: 'NCAP', truncated: false,
    weeks: [
      { week_start: '2026-10-18', week_end: '2026-10-22', week_label: '18 - 22 Oct 2026', schedules: [schedule(15, 'PDS-015', '2026-10-19'), schedule(18, 'PDS-018', '2026-10-21')] },
      { week_start: '2026-11-01', week_end: '2026-11-05', week_label: '01 - 05 Nov 2026', schedules: [schedule(26, 'PDS-026', '2026-11-03')] },
    ],
  }
  const onOpen = vi.fn()
  render(<TenantUpcomingResults result={result} onOpen={onOpen} />)
  expect(screen.getAllByRole('region').map((r) => r.getAttribute('aria-label'))).toEqual([
    'Week 18 - 22 Oct 2026', 'Week 01 - 05 Nov 2026',
  ])
  expect(screen.getAllByText('Asha RM')).toHaveLength(3)
  fireEvent.click(screen.getByRole('button', { name: /PDS-018/ }))
  expect(onOpen).toHaveBeenCalledWith(18, 'PDS-018')
})

it('shows a clear message and no week containers when nothing is upcoming', () => {
  render(<TenantUpcomingResults result={{ tenant_id: 7, tenant_name: 'NCAP', truncated: false, weeks: [] }} onOpen={vi.fn()} />)
  expect(screen.getByRole('status').textContent).toBe('No upcoming PDS schedules found for NCAP.')
  expect(screen.queryAllByRole('region')).toHaveLength(0)
})
