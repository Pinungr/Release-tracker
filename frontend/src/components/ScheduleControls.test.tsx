import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { AuditEvent, BookingDetail, DayView, DocumentTypeConfig, PublicSettings } from '../types'
import { api } from '../services/api'
import { AdminPanel } from './AdminPanel'
import { AuditHistory } from './AuditHistory'
import { ChangeDetailsPage } from './ChangeDetailsPage'
import { DaySchedule } from './DaySchedule'
import { ToastProvider } from './ToastNotification'

// Every API call resolves to an empty list unless a test says otherwise.
vi.mock('../services/api', () => {
  const calls: Record<string, ReturnType<typeof vi.fn>> = {}
  return {
    api: new Proxy(calls, {
      get: (target, key: string) => (target[key] ??= vi.fn().mockResolvedValue([])),
    }),
    ApiError: class extends Error {},
  }
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

const settings = { max_file_size_mb: 20, jira_required_at_booking: false, document_catalog: [] } as unknown as PublicSettings

function booking(overrides: Partial<BookingDetail> = {}): BookingDetail {
  return {
    id: 1, booking_reference: 'pds-001', tenant_name: 'EPCAT', tenant_id: 1,
    deployment_date: '2026-10-11', slot_number: 1, slot_label: 'Slot 1', slot_time: '09:00 PM - 05:00 AM',
    status: 'BOOKED', is_emergency: false, is_past: false, is_locked: false, lock_reason: 'NONE',
    created_by_user_id: 1, assigned_users: [], change_number: null, jira_number: null, jira_url: null,
    git_repository: 'https://example.com/repo', attachments: [],
    documents: { items: [], missing_labels: [], percent: 100, complete: true, provided_required: 0, total_required: 0 },
    collaborators: [{ user_id: 7, full_name: 'Pool User', username: 'pool', email: 'pool@example.com', assigned_at: '' }],
    can_edit: true, can_cancel: true, can_reschedule: true, can_assign_rm: false, can_assign_self: false,
    can_start_work: false, can_manage_attachments: true, can_download_attachments: true, can_manage_collaborators: true,
    ...overrides,
  } as BookingDetail
}

function details(detail: BookingDetail) {
  render(<ToastProvider><ChangeDetailsPage open onClose={vi.fn()} booking={detail} loading={false} settings={settings}
    isAdmin={false} timezone="Asia/Kolkata" userId={1} onEdit={vi.fn()} onChanged={vi.fn()} /></ToastProvider>)
}

describe('collaborator modal', () => {
  it('keeps a removal when the scheduler searches afterwards', async () => {
    vi.mocked(api.getCollaboratorCandidates).mockResolvedValue([
      { id: 7, full_name: 'Pool User', username: 'pool', email: 'pool@example.com', selected: true },
    ])
    vi.mocked(api.setCollaborators).mockResolvedValue(booking({ collaborators: [] }))
    details(booking())
    fireEvent.click(screen.getByRole('button', { name: 'Collaborators' }))
    const box = await screen.findByRole('checkbox', { name: /Pool User/ })
    expect((box as HTMLInputElement).checked).toBe(true)

    fireEvent.click(box)
    fireEvent.change(screen.getByLabelText('Search the Member Pool'), { target: { value: 'poo' } })
    await waitFor(() => expect(api.getCollaboratorCandidates).toHaveBeenCalledWith(1, 'poo'))
    expect((screen.getByRole('checkbox', { name: /Pool User/ }) as HTMLInputElement).checked).toBe(false)

    fireEvent.click(screen.getByRole('button', { name: 'Save collaborators' }))
    await waitFor(() => expect(api.setCollaborators).toHaveBeenCalledWith(1, []))
  })

  it('is offered only when the backend allows collaborator changes', () => {
    details(booking({ can_manage_collaborators: false }))
    expect(screen.queryByRole('button', { name: 'Collaborators' })).toBeNull()
  })
})

it('explains when an Admin/RM unlock lifted the automatic lock', () => {
  details(booking({ lock_overridden: true }))
  expect(screen.getByText('Automatic lock lifted')).toBeTruthy()
})

describe('day-level automatic lock control', () => {
  const day = {
    day: '2026-10-11', weekday: 'Sunday', date_label: '11 Oct', is_today: false, is_past: false, holiday: null,
    custom_slot_count: null, regular_slots_total: 0, regular_slots_used: 0, slots: [], emergency_open: false,
    emergency_closed_reason: null, emergency_bookings: [], automatic_lock: true, date_unlocked: false,
  } as DayView

  function show(view: DayView, isAdmin: boolean, readOnly = false) {
    const onToggleLock = vi.fn()
    render(<DaySchedule day={view} today="2026-09-30" isAdmin={isAdmin} readOnly={readOnly} myBookingIds={new Set()}
      visibleSlots={[]} filtered={false} onBook={vi.fn()} onBookEmergency={vi.fn()} onOpenBooking={vi.fn()}
      onToggleFreeze={vi.fn()} onToggleLock={onToggleLock} onAdjustCapacity={vi.fn()} />)
    return onToggleLock
  }

  it('lets Admin/RM unlock and restore the whole date', () => {
    const onToggleLock = show(day, true)
    expect(screen.getByText('Automatic lock')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Unlock date/ }))
    expect(onToggleLock).toHaveBeenCalledWith(day, null)
    cleanup()
    show({ ...day, date_unlocked: true }, true)
    expect(screen.getByText('Unlocked')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Restore lock/ })).toBeTruthy()
  })

  it('shows tenants and Management the state without controls', () => {
    show(day, false)
    expect(screen.getByText('Automatic lock')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Unlock date|Restore lock/ })).toBeNull()
    cleanup()
    show(day, true, true)
    expect(screen.queryByRole('button', { name: /Unlock date|Restore lock/ })).toBeNull()
  })
})

describe('document upload configuration', () => {
  const types: DocumentTypeConfig[] = [
    { id: 1, key: 'IMPLEMENTATION_PLAN', label: 'Implementation Document', description: null, is_active: true, is_required: true, allow_multiple: false, display_order: 1, file_count: 4, multi_file_schedules: 0 },
    { id: 2, key: 'DBA_SCRIPT', label: 'DBA Scripts', description: null, is_active: true, is_required: true, allow_multiple: false, display_order: 2, file_count: 9, multi_file_schedules: 2 },
  ]

  async function open() {
    vi.mocked(api.getDocumentTypes).mockResolvedValue(types)
    render(<ToastProvider><AdminPanel open onClose={vi.fn()} timezone="Asia/Kolkata" currentUserId={1} isOwner onChanged={vi.fn()} /></ToastProvider>)
    fireEvent.click(screen.getByRole('button', { name: /Document uploads/ }))
    await screen.findByLabelText('Name of DBA Scripts')
  }

  it('changes requirement, file mode and order through the API', async () => {
    await open()
    vi.mocked(api.updateDocumentType).mockResolvedValue(types)
    vi.mocked(api.reorderDocumentTypes).mockResolvedValue(types)
    fireEvent.change(screen.getByLabelText('DBA Scripts requirement'), { target: { value: 'optional' } })
    await waitFor(() => expect(api.updateDocumentType).toHaveBeenCalledWith(2, { is_required: false }))
    fireEvent.change(screen.getByLabelText('DBA Scripts file mode'), { target: { value: 'multiple' } })
    await waitFor(() => expect(api.updateDocumentType).toHaveBeenCalledWith(2, { allow_multiple: true }))
    fireEvent.click(screen.getByRole('button', { name: 'Move DBA Scripts up' }))
    await waitFor(() => expect(api.reorderDocumentTypes).toHaveBeenCalledWith([2, 1]))
  })

  it('warns that schedules keep files from before a switch to Single', async () => {
    await open()
    expect(screen.getByText(/2 schedules kept the several files/)).toBeTruthy()
    // Types with uploaded files can only be disabled, never deleted.
    expect(screen.queryByRole('button', { name: 'Delete DBA Scripts' })).toBeNull()
  })
})

describe('audit display', () => {
  it('names the real actor and how they had access', async () => {
    const event: AuditEvent = {
      id: 1, booking_reference: 'pds-001', tenant_name: 'EPCAT', event_type: 'DOCUMENTS_DELETED', actor_type: 'USER',
      requester_email: 'pool@example.com', admin_username: null, actor_access: 'COLLABORATOR', override_reason: null,
      old_values: { files: ['rollback.sql (DBA Scripts)', 'validation.sql (DBA Scripts)'], attachment_ids: [2, 3], count: 2 },
      new_values: null, created_at: '2026-09-30T10:00:00',
    }
    vi.mocked(api.getAudit).mockResolvedValue([event])
    render(<AuditHistory timezone="Asia/Kolkata" />)
    expect(await screen.findByText('Selected documents removed')).toBeTruthy()
    expect(screen.getByText('pool@example.com')).toBeTruthy()
    expect(screen.getByText('· as collaborator')).toBeTruthy()
    // Shown in the summary line and again in the expandable event details.
    expect(screen.getAllByText('rollback.sql (DBA Scripts), validation.sql (DBA Scripts)').length).toBeGreaterThan(0)
  })
})
