import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ScheduleSearch } from './ScheduleSearch'
import { ScheduleFilters } from './ScheduleFilters'
import { api } from '../services/api'

vi.mock('../services/api', () => ({
  api: {
    searchSchedules: vi.fn(),
    getScheduleHistory: vi.fn(),
    getTenantUpcoming: vi.fn(),
    lookupTenants: vi.fn(),
  },
  ApiError: class extends Error {},
}))

const NCAP = { id: 7, name: 'NCAP', tenant_code: 'NCAP', is_active: true }
const historyRow = {
  id: 9, booking_reference: 'PDS-009', tenant_id: 7, tenant_name: 'NCAP', deployment_date: '2026-09-10',
  slot_number: 1, is_emergency: false, status: 'COMPLETED', change_number: 'CHG-9', jira_number: null,
  jira_url: null, release_managers: ['Asha RM'],
}

beforeEach(() => {
  vi.mocked(api.searchSchedules).mockResolvedValue([{ id: 4, booking_reference: 'pds-001', tenant_name: 'Tenant', deployment_date: '2026-01-01', status: 'COMPLETED', change_number: 'CHG-1' }] as never)
  vi.mocked(api.getScheduleHistory).mockResolvedValue([historyRow] as never)
  vi.mocked(api.getTenantUpcoming).mockResolvedValue({ tenant_id: NCAP.id, tenant_name: NCAP.name, weeks: [], truncated: false })
  vi.mocked(api.lookupTenants).mockResolvedValue([NCAP])
})
afterEach(() => { cleanup(); vi.clearAllMocks() })

const box = () => screen.getByRole('combobox', { name: /Search Schedule No\. or tenant/ })

it('opens a completed schedule returned by global number search', async () => {
  const onOpen = vi.fn()
  render(<ScheduleSearch onOpen={onOpen} />)
  fireEvent.change(box(), { target: { value: 'pds-001' } })
  fireEvent.click(screen.getByRole('button', { name: 'Find schedule' }))
  await waitFor(() => expect(api.searchSchedules).toHaveBeenCalledWith('pds-001'))
  expect(api.getScheduleHistory).not.toHaveBeenCalled()
  fireEvent.click(await screen.findByRole('button', { name: /pds-001.*Tenant/ }))
  expect(onOpen).toHaveBeenCalledWith(4, 'pds-001')
})

it('searches a tenant\'s history with a Days range from the same box', async () => {
  render(<ScheduleSearch onOpen={vi.fn()} />)
  fireEvent.focus(box())
  fireEvent.change(box(), { target: { value: 'NCA' } })
  fireEvent.click(await screen.findByRole('option', { name: /NCAP/ }))
  fireEvent.change(screen.getByLabelText('Days'), { target: { value: '30' } })
  fireEvent.click(screen.getByRole('button', { name: 'Find schedule' }))
  await waitFor(() => expect(api.getScheduleHistory).toHaveBeenCalled())
  expect(vi.mocked(api.getScheduleHistory).mock.calls[0][0]).toMatchObject({
    tenantId: 7, q: undefined, window: { days: 30, dateFrom: '', dateTo: '' },
  })
  expect(await screen.findByText('NCAP · last 30 days · newest first')).toBeTruthy()
  expect(screen.getByRole('button', { name: /PDS-009/ })).toBeTruthy()
})

it('shows upcoming schedules when an exact tenant name is entered without dates', async () => {
  render(<ScheduleSearch onOpen={vi.fn()} />)
  fireEvent.change(box(), { target: { value: 'ncap' } })
  await waitFor(() => expect(api.lookupTenants).toHaveBeenCalledWith('ncap'))
  await new Promise((r) => setTimeout(r, 250))
  fireEvent.click(screen.getByRole('button', { name: 'Find schedule' }))
  await waitFor(() => expect(api.getTenantUpcoming).toHaveBeenCalledWith(7))
  expect(api.getScheduleHistory).not.toHaveBeenCalled()
  expect(api.searchSchedules).not.toHaveBeenCalled()
})

it('runs a date-range-only search across all tenants', async () => {
  render(<ScheduleSearch onOpen={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('From date'), { target: { value: '2026-09-01' } })
  fireEvent.change(screen.getByLabelText('To date'), { target: { value: '2026-09-30' } })
  fireEvent.click(screen.getByRole('button', { name: 'Find schedule' }))
  await waitFor(() => expect(api.getScheduleHistory).toHaveBeenCalled())
  expect(vi.mocked(api.getScheduleHistory).mock.calls[0][0]).toMatchObject({
    tenantId: undefined, window: { days: null, dateFrom: '2026-09-01', dateTo: '2026-09-30' },
  })
})

it('clears every filter and the results', async () => {
  render(<ScheduleSearch onOpen={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('Days'), { target: { value: '15' } })
  fireEvent.click(screen.getByRole('button', { name: 'Find schedule' }))
  await screen.findByRole('button', { name: /PDS-009/ })
  fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
  expect((screen.getByLabelText('Days') as HTMLSelectElement).value).toBe('')
  expect(screen.queryByRole('button', { name: /PDS-009/ })).toBeNull()
})

it('board search offers a tenant\'s upcoming view', async () => {
  const onPickTenant = vi.fn()
  render(
    <ScheduleFilters query="NCA" onQueryChange={vi.fn()} filter="ALL" onFilterChange={vi.fn()}
      technologies={[]} isAdmin={false} resultCount={null} onPickTenant={onPickTenant} />,
  )
  fireEvent.focus(screen.getByRole('combobox', { name: 'Search deployments' }))
  fireEvent.click(await screen.findByRole('option', { name: /Show upcoming schedules for NCAP/ }))
  expect(onPickTenant).toHaveBeenCalledWith(NCAP)
})

it('hides the week filter chips while a tenant view is showing', () => {
  render(
    <ScheduleFilters query="NCAP" onQueryChange={vi.fn()} filter="ALL" onFilterChange={vi.fn()}
      technologies={[]} isAdmin={false} resultCount={3} onPickTenant={vi.fn()} tenantMode />,
  )
  expect(screen.queryByRole('button', { name: 'Available' })).toBeNull()
  expect(screen.queryByText(/slots? match/)).toBeNull()
})
