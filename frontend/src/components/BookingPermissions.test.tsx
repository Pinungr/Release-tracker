import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { BookingDetail, PublicSettings } from '../types'
import { api } from '../services/api'
import { ChangeDetailsPage } from './ChangeDetailsPage'
import { RescheduleModal } from './RescheduleModal'
import { ToastProvider } from './ToastNotification'

vi.mock('../services/api', () => ({
  api: { listUsers: vi.fn().mockResolvedValue([]), setBookingStatus: vi.fn().mockResolvedValue({}), reopenBooking: vi.fn().mockResolvedValue({}), downloadAttachment: vi.fn().mockResolvedValue(undefined), getRescheduleOptions: vi.fn(), getBookingComments: vi.fn().mockResolvedValue([]), getBookingAudit: vi.fn().mockResolvedValue([]) },
  ApiError: class extends Error {},
}))

afterEach(() => { cleanup(); vi.clearAllMocks() })

const settings = {
  max_file_size_mb: 20, jira_required_at_booking: false,
  document_catalog: [{ category: 'TEST_RESULTS', label: 'Test results', required: true, multiple: false }],
} as PublicSettings

function booking(overrides: Partial<BookingDetail> = {}): BookingDetail {
  return {
    id: 1, booking_reference: 'PDS-20261004-001', tenant_name: 'Example', tenant_id: 1,
    deployment_date: '2026-10-04', slot_number: 1, slot_label: 'Slot 1', slot_time: '09:00 PM - 05:00 AM',
    status: 'BOOKED', is_emergency: false, is_past: false, is_locked: false, lock_reason: 'NONE',
    created_by_user_id: 1, assigned_users: [{ user_id: 2, full_name: 'RM User', username: 'rm', email: 'rm@example.com', assigned_at: '' }],
    collaborators: [], can_assign_self: false,
    change_number: null, jira_number: null, jira_url: null, git_repository: 'https://example.com/repo',
    attachments: [{ id: 10, category: 'TEST_RESULTS', original_filename: 'evidence.pdf', size_bytes: 42 }],
    documents: { items: [], missing_labels: [], percent: 100, complete: true, provided_required: 1, total_required: 1 },
    can_edit: true, can_cancel: true, can_reschedule: true, can_assign_rm: true,
    can_start_work: true, can_manage_attachments: true, can_download_attachments: true,
    ...overrides,
  } as BookingDetail
}

function show(detail: BookingDetail, isAdmin = true, userId = 1, readOnly = false, onChanged = vi.fn()) {
  return render(<ToastProvider><ChangeDetailsPage open onClose={vi.fn()} booking={detail}
    loading={false} settings={settings} isAdmin={isAdmin} readOnly={readOnly} timezone="Asia/Kolkata" userId={userId}
    onEdit={vi.fn()} onChanged={onChanged} /></ToastProvider>)
}

describe('authoritative booking permissions', () => {
  it.each([
    ['CURRENT_DATE', 'Scheduling for today is protected. Additional uploads may be unlocked; existing files remain protected.'],
    ['PAST_DATE', 'Scheduling on this historical record is protected. Additional uploads may be unlocked within seven days.'],
    ['AUTOMATIC_DATE_FREEZE', 'This deployment date is inside the automatic lock window. The Owner or a Release Manager can unlock it.'],
    ['MANUAL_SLOT_FREEZE', 'This slot was manually frozen by the Owner or a Release Manager.'],
  ] as const)('hides modification controls and explains %s for Admin', (reason, message) => {
    show(booking({ lock_reason: reason, is_past: reason === 'PAST_DATE', is_locked: true, can_edit: false, can_cancel: false,
      can_reschedule: false, can_assign_rm: false, can_start_work: false, can_manage_attachments: false }))
    expect(screen.getByText(message)).toBeTruthy()
    for (const name of [/^Edit$/, /^Reschedule$/, /^Cancel$/, /Save Release Manager assignment/, /^Start work$/, /Upload|Replace|Remove/]) {
      expect(screen.queryByRole('button', { name })).toBeNull()
    }
    if (reason !== 'MANUAL_SLOT_FREEZE') expect(screen.queryByText(/This slot was manually frozen/)).toBeNull()
  })

  it('keeps editable future booking actions', async () => {
    show(booking())
    expect(screen.getByRole('button', { name: 'Edit' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Reschedule' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeTruthy()
  })

  it('shows start-work actions only when the Release Manager is assigned', async () => {
    show(booking({ can_assign_rm: false, can_start_work: true }), true, 2)
    fireEvent.click(screen.getByRole('button', { name: 'Download evidence.pdf' }))
    await waitFor(() => expect(api.downloadAttachment).toHaveBeenCalledWith(1, 10, 'evidence.pdf'))
    expect(screen.getByText('An assigned Release Manager adds the Change Number when work begins. The Jira reference remains separate.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Start work' })).toBeTruthy()

    cleanup()
    show(booking({ can_assign_rm: false, can_start_work: false }), true, 2)
    expect(screen.queryByRole('button', { name: 'Start work' })).toBeNull()
  })

  it('renders only API-provided normal reschedule destinations', async () => {
    vi.mocked(api.getRescheduleOptions).mockResolvedValue([{
      deployment_date: '2026-09-27', weekday: 'Sunday', date_label: '27 Sep 2026',
      slot_number: 2, slot_name: 'Slot 2', time_label: '09:00 PM - 05:00 AM',
    }])
    render(<ToastProvider><RescheduleModal open onClose={vi.fn()} booking={booking()} onDone={vi.fn()} /></ToastProvider>)
    await waitFor(() => expect(screen.getByText(/27 Sep 2026/)).toBeTruthy())
    expect(screen.queryByText(/Saturday|Friday/)).toBeNull()
    expect(screen.queryByDisplayValue('2026-09-26')).toBeNull()
  })
})

it('offers Admin closure for open and historical in-progress records using API permissions', async () => {
  show(booking({ can_close: false }))
  expect(screen.queryByRole('button', { name: 'Complete / Close' })).toBeNull()
  cleanup()
  show(booking({ can_close: true, can_edit: false, can_cancel: false, can_reschedule: false, lock_reason: 'CURRENT_DATE', attachments_add_only: true }))
  expect(screen.getByRole('button', { name: 'Complete / Close' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Complete / Close' }))
  await waitFor(() => expect(api.setBookingStatus).toHaveBeenCalledWith(1, 'COMPLETED'))
  expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull()
  cleanup()
  show(booking({ status: 'IN_PROGRESS', can_close: true, can_edit: false, lock_reason: 'PAST_DATE' }))
  expect(screen.getByRole('button', { name: 'Complete / Close' })).toBeTruthy()
  cleanup()
  show(booking({ status: 'COMPLETED', can_reschedule: false, can_start_work: false, can_cancel: false }))
  expect(screen.queryByRole('button', { name: 'Reschedule' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Complete / Close' })).toBeNull()
})

describe('reopen a closed schedule', () => {
  it.each([
    [1, 'CURRENT_DATE'], [2, 'PAST_DATE'],
  ] as const)('lets Admin/RM %s reopen a record protected by %s', async (userId, lockReason) => {
    const onChanged = vi.fn()
    show(booking({ status: 'COMPLETED', can_reopen: true, can_close: false, can_edit: false,
      can_cancel: false, can_reschedule: false, can_assign_rm: false, can_start_work: false,
      can_manage_attachments: false, lock_reason: lockReason, is_locked: true, attachments_add_only: true }), true, userId, false, onChanged)
    fireEvent.click(screen.getByRole('button', { name: 'Reopen schedule' }))
    await waitFor(() => expect(api.reopenBooking).toHaveBeenCalledWith(1))
    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce())
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Reschedule' })).toBeNull()
  })

  it.each([
    [false, false, true], [true, true, true], [true, false, false],
  ])('honors Admin=%s, Management=%s and backend permission=%s', (isAdmin, readOnly, canReopen) => {
    show(booking({ status: 'COMPLETED', can_reopen: canReopen }), isAdmin, 1, readOnly)
    expect(screen.queryByRole('button', { name: 'Reopen schedule' })).toBeNull()
    expect(api.reopenBooking).not.toHaveBeenCalled()
  })

  it('reports a failed reopen without refreshing or changing the displayed status', async () => {
    vi.mocked(api.reopenBooking).mockRejectedValueOnce(new Error('Unavailable'))
    const onChanged = vi.fn()
    show(booking({ status: 'COMPLETED', can_reopen: true }), true, 1, false, onChanged)
    fireEvent.click(screen.getByRole('button', { name: 'Reopen schedule' }))
    expect(await screen.findByText('Could not reopen the schedule')).toBeTruthy()
    expect(onChanged).not.toHaveBeenCalled()
    expect(screen.getAllByText('COMPLETED').length).toBeGreaterThan(0)
    expect((screen.getByRole('button', { name: 'Reopen schedule' }) as HTMLButtonElement).disabled).toBe(false)
  })
})
