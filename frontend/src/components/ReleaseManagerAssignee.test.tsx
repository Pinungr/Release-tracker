import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../services/api'
import type { BookingDetail, GroupMember } from '../types'
import { ReleaseManagerAssignee } from './ReleaseManagerAssignee'
import { ToastProvider } from './ToastNotification'

vi.mock('../services/api', () => ({
  api: { searchReleaseManagers: vi.fn(), assignBookingUsers: vi.fn(), assignBookingToMe: vi.fn() },
  ApiError: class extends Error {},
}))
const rahul = { id: 2, full_name: 'Rahul Sharma', username: 'rahul', email: 'rahul@example.com', is_owner: false, is_active: true } satisfies GroupMember
const mangesh = { ...rahul, id: 3, full_name: 'Mangesh Patil', username: 'mangesh' }
const detail = (user = rahul) => ({
  id: 10, booking_reference: 'PDS-010', can_assign_rm: true, can_assign_self: true,
  assigned_users: [{ user_id: user.id, full_name: user.full_name, username: user.username, email: user.email, assigned_at: '' }],
} as BookingDetail)
function show(booking = detail()) {
  const onChanged = vi.fn()
  render(<ToastProvider><ReleaseManagerAssignee booking={booking} onChanged={onChanged} /></ToastProvider>)
  return { input: screen.getByRole('combobox', { name: 'Release Manager assignee' }) as HTMLInputElement, onChanged }
}
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.searchReleaseManagers).mockResolvedValue([mangesh])
  vi.mocked(api.assignBookingUsers).mockResolvedValue(detail(mangesh))
  vi.mocked(api.assignBookingToMe).mockResolvedValue(detail(mangesh))
})
afterEach(cleanup)

it('shows the saved full name in the input without tags or a save button', () => {
  const { input } = show()
  expect(input.value).toBe('Rahul Sharma')
  expect(screen.queryByRole('button', { name: /Remove|Save assignment/ })).toBeNull()
  expect(screen.queryByRole('listbox')).toBeNull()
  expect(api.searchReleaseManagers).not.toHaveBeenCalled()
})

it('searches after two letters and immediately replaces the saved assignee', async () => {
  const { input, onChanged } = show()
  fireEvent.change(input, { target: { value: 'm' } })
  expect(screen.queryByRole('listbox')).toBeNull()
  expect(api.searchReleaseManagers).not.toHaveBeenCalled()
  fireEvent.change(input, { target: { value: 'ma' } })
  fireEvent.click(await screen.findByRole('option', { name: /Mangesh Patil/ }))
  await waitFor(() => expect(input.value).toBe('Mangesh Patil'))
  expect(api.assignBookingUsers).toHaveBeenCalledWith(10, [3])
  expect(onChanged).toHaveBeenCalledTimes(1)
  expect(screen.queryByRole('listbox')).toBeNull()
})

it('assigns to self and displays the returned full name immediately', async () => {
  const { input, onChanged } = show()
  fireEvent.click(screen.getByRole('button', { name: 'Assign to me' }))
  await waitFor(() => expect(input.value).toBe('Mangesh Patil'))
  expect(api.assignBookingToMe).toHaveBeenCalledWith(10)
  expect(onChanged).toHaveBeenCalledTimes(1)
})

it('restores the existing assignee if saving fails', async () => {
  vi.mocked(api.assignBookingUsers).mockRejectedValueOnce(new Error('offline'))
  const { input, onChanged } = show()
  fireEvent.change(input, { target: { value: 'ma' } })
  fireEvent.click(await screen.findByRole('option', { name: /Mangesh Patil/ }))
  await screen.findByText('Could not update the assignee')
  expect(input.value).toBe('Rahul Sharma')
  expect(onChanged).not.toHaveBeenCalled()
})

it('supports keyboard replacement and cancels incomplete edits without unassigning', async () => {
  const { input } = show()
  fireEvent.change(input, { target: { value: '' } })
  fireEvent.keyDown(input, { key: 'Escape' })
  expect(input.value).toBe('Rahul Sharma')
  expect(api.assignBookingUsers).not.toHaveBeenCalled()
  fireEvent.change(input, { target: { value: 'ma' } })
  await screen.findByRole('option', { name: /Mangesh Patil/ })
  fireEvent.keyDown(input, { key: 'ArrowDown' })
  fireEvent.keyDown(input, { key: 'Enter' })
  await waitFor(() => expect(input.value).toBe('Mangesh Patil'))
})

it('replaces all legacy assignees with the selected person', async () => {
  const { input } = show({ ...detail(), assigned_users: [...detail().assigned_users, ...detail(mangesh).assigned_users] })
  expect(screen.getByText(/multiple existing assignees/)).toBeTruthy()
  fireEvent.change(input, { target: { value: 'ma' } })
  fireEvent.click(await screen.findByRole('option', { name: /Mangesh Patil/ }))
  await waitFor(() => expect(api.assignBookingUsers).toHaveBeenCalledWith(10, [3]))
})
