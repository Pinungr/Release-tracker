import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { BookingDetail, PublicSettings } from '../types'
import { api } from '../services/api'
import { BookingDetailsDrawer } from './BookingDetailsDrawer'
import { RescheduleModal } from './RescheduleModal'
import { ToastProvider } from './ToastNotification'

vi.mock('../services/api', () => ({
  api: { listUsers: vi.fn().mockResolvedValue([]), downloadAttachment: vi.fn().mockResolvedValue(undefined), getRescheduleOptions: vi.fn() },
  ApiError: class extends Error {},
}))

afterEach(cleanup)

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
    change_number: null, jira_number: null, jira_url: null, git_repository: 'https://example.com/repo',
    attachments: [{ id: 10, category: 'TEST_RESULTS', original_filename: 'evidence.pdf', size_bytes: 42 }],
    documents: { items: [], missing_labels: [], percent: 100, complete: true, provided_required: 1, total_required: 1 },
    can_edit: true, can_cancel: true, can_reschedule: true, can_assign_rm: true,
    can_start_work: true, can_manage_attachments: true, can_download_attachments: true,
    ...overrides,
  } as BookingDetail
}

function show(detail: BookingDetail, isAdmin = true, userId = 1) {
  return render(<ToastProvider><BookingDetailsDrawer open onClose={vi.fn()} booking={detail}
    loading={false} settings={settings} isAdmin={isAdmin} timezone="Asia/Kolkata" userId={userId}
    onEdit={vi.fn()} onChanged={vi.fn()} /></ToastProvider>)
}

describe('authoritative booking permissions', () => {
  it.each([
    ['CURRENT_DATE', 'This booking is locked because deployments scheduled for today are read-only.'],
    ['PAST_DATE', 'This booking is historical and cannot be modified.'],
    ['AUTOMATIC_DATE_FREEZE', 'This deployment date is inside the protected scheduling window.'],
    ['MANUAL_SLOT_FREEZE', 'This slot was manually frozen by an administrator.'],
  ] as const)('hides modification controls and explains %s for Admin', (reason, message) => {
    show(booking({ lock_reason: reason, is_past: reason === 'PAST_DATE', is_locked: true, can_edit: false, can_cancel: false,
      can_reschedule: false, can_assign_rm: false, can_start_work: false, can_manage_attachments: false }))
    expect(screen.getByText(message)).toBeTruthy()
    for (const name of [/^Edit$/, /^Reschedule$/, /^Cancel$/, /Save RM assignment/, /^Start work$/, /Upload|Replace|Remove/]) {
      expect(screen.queryByRole('button', { name })).toBeNull()
    }
    if (reason !== 'MANUAL_SLOT_FREEZE') expect(screen.queryByText(/This slot was manually frozen/)).toBeNull()
  })

  it('keeps editable future booking actions', async () => {
    show(booking())
    await waitFor(() => expect(api.listUsers).toHaveBeenCalled())
    expect(screen.getByRole('button', { name: 'Edit' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Reschedule' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeTruthy()
  })

  it('lets assigned RM download while withholding document mutations', async () => {
    show(booking({ can_edit: false, can_cancel: false, can_reschedule: false,
      can_assign_rm: false, can_manage_attachments: false }), false, 2)
    fireEvent.click(screen.getByRole('button', { name: 'Download evidence.pdf' }))
    await waitFor(() => expect(api.downloadAttachment).toHaveBeenCalledWith(1, 10, 'evidence.pdf'))
    expect(screen.queryByRole('button', { name: /Upload|Replace|Remove/ })).toBeNull()
    expect(screen.getByText('Add the Change Number when RM work begins. Jira reference, if provided during booking, remains separate.')).toBeTruthy()
    expect(screen.getByText('Not provided')).toBeTruthy()
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
