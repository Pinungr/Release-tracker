import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { Attachment, BookingDetail, DayView, PublicSettings, SlotView } from '../types'
import { api } from '../services/api'
import { DeploymentSlot } from './DeploymentSlot'
import { DocumentUploader } from './DocumentUploader'
import { ToastProvider } from './ToastNotification'

vi.mock('../services/api', () => ({
  api: {
    uploadAttachments: vi.fn(),
    deleteAttachment: vi.fn(),
    deleteAttachments: vi.fn(),
    downloadAttachment: vi.fn().mockResolvedValue(undefined),
  },
  ApiError: class extends Error {},
}))

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

const settings = {
  max_file_size_mb: 20,
  jira_required_at_booking: false,
  document_catalog: [
    { category: 'IMPLEMENTATION_PLAN', label: 'Implementation Document', required: true, multiple: false },
    { category: 'DBA_SCRIPT', label: 'DBA Scripts', required: true, multiple: true },
  ],
} as PublicSettings

function file(id: number, category: string, name: string): Attachment {
  return {
    id, category, category_label: category, original_filename: name, size_bytes: 10,
    content_type: null, uploaded_at: '2026-10-01T09:00:00', uploaded_by: 'pinaki@example.com',
  }
}

function booking(attachments: Attachment[], overrides: Partial<BookingDetail> = {}): BookingDetail {
  return {
    id: 7, attachments, can_manage_attachments: true, can_download_attachments: true, ...overrides,
  } as BookingDetail
}

function show(detail: BookingDetail, onUpdated = vi.fn()) {
  render(<ToastProvider><DocumentUploader booking={detail} settings={settings} timezone="Asia/Kolkata" onUpdated={onUpdated} /></ToastProvider>)
  return onUpdated
}

const scripts = [file(1, 'DBA_SCRIPT', 'deployment.sql'), file(2, 'DBA_SCRIPT', 'rollback.sql'), file(3, 'DBA_SCRIPT', 'validation.sql')]

describe('Manage Attachments', () => {
  it('deletes only the selected files of a multiple-file type', async () => {
    vi.mocked(api.deleteAttachments).mockResolvedValue(booking([scripts[0]]))
    const onUpdated = show(booking([file(9, 'IMPLEMENTATION_PLAN', 'plan.docx'), ...scripts]))
    expect(screen.getAllByText(/pinaki@example.com/)).toHaveLength(4)

    fireEvent.click(screen.getByLabelText('Select rollback.sql'))
    fireEvent.click(screen.getByLabelText('Select validation.sql'))
    fireEvent.click(screen.getByRole('button', { name: /Delete selected \(2\)/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(api.deleteAttachments).toHaveBeenCalledWith(7, [2, 3]))
    expect(onUpdated).toHaveBeenCalled()
  })

  it('keeps the final file of a required type', () => {
    show(booking([file(9, 'IMPLEMENTATION_PLAN', 'plan.docx'), ...scripts]))
    // Single required file: removal disabled, Replace offered instead.
    expect((screen.getByRole('button', { name: 'Remove plan.docx' }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByRole('button', { name: /Replace/ })).toBeTruthy()

    fireEvent.click(screen.getByLabelText('Select all'))
    expect((screen.getByRole('button', { name: /Delete selected \(3\)/ }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('uploads several files in one operation for a multiple-file type', async () => {
    vi.mocked(api.uploadAttachments).mockResolvedValue(booking(scripts))
    show(booking([file(9, 'IMPLEMENTATION_PLAN', 'plan.docx')]))
    const input = screen.getByTestId('upload-DBA_SCRIPT') as HTMLInputElement
    expect(input.multiple).toBe(true)
    expect((screen.getByTestId('upload-IMPLEMENTATION_PLAN') as HTMLInputElement).multiple).toBe(false)
    const files = [new File(['a'], 'a.sql'), new File(['b'], 'b.sql')]
    fireEvent.change(input, { target: { files } })
    await waitFor(() => expect(api.uploadAttachments).toHaveBeenCalledWith(7, 'DBA_SCRIPT', files))
  })

  it('shows files of disabled types for download but offers no upload for them', () => {
    show(booking([file(5, 'INVENTORY', 'inventory.xlsx')]))
    expect(screen.getByText('Documents from retired types')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Download inventory.xlsx' })).toBeTruthy()
    expect(screen.queryByTestId('upload-INVENTORY')).toBeNull()
  })

  it('is read-only without attachment permission', () => {
    show(booking(scripts, { can_manage_attachments: false }))
    expect(screen.queryByRole('button', { name: /Upload|Replace|Add files|Remove|Delete selected/ })).toBeNull()
    expect(screen.queryByLabelText('Select all')).toBeNull()
    expect(screen.getByRole('button', { name: 'Download rollback.sql' })).toBeTruthy()
  })
})

describe('automatic lock controls', () => {
  const day = { day: '2026-10-05', weekday: 'Monday', date_label: '5 Oct', holiday: null } as DayView
  const slot = {
    slot_number: 1, name: 'Slot 1', time_label: '9 PM - 5 AM', state: 'AVAILABLE', bookable: false,
    manually_frozen: false, automatic_lock: true, lock_override: null, booking: null, unavailable_reason: 'Locked',
  } as unknown as SlotView

  function slotRow(props: { isAdmin: boolean; readOnly?: boolean; slot?: SlotView }) {
    const onToggleLock = vi.fn()
    render(<DeploymentSlot day={day} slot={props.slot ?? slot} isMine={false} isAdmin={props.isAdmin} readOnly={props.readOnly}
      isHistorical={false} onBook={vi.fn()} onOpenBooking={vi.fn()} onToggleFreeze={vi.fn()} onToggleLock={onToggleLock} />)
    return onToggleLock
  }

  it('offers Unlock and Restore lock to Admin/RM only', () => {
    const onToggleLock = slotRow({ isAdmin: true })
    fireEvent.click(screen.getByRole('button', { name: /^Unlock$/ }))
    expect(onToggleLock).toHaveBeenCalledWith(day, slot)
    cleanup()

    slotRow({ isAdmin: true, slot: { ...slot, lock_override: 'SLOT' } })
    expect(screen.getByRole('button', { name: /Restore lock/ })).toBeTruthy()
    cleanup()

    slotRow({ isAdmin: false })
    expect(screen.queryByRole('button', { name: /Unlock|Restore lock/ })).toBeNull()
    cleanup()

    slotRow({ isAdmin: true, readOnly: true })
    expect(screen.queryByRole('button', { name: /Unlock|Restore lock/ })).toBeNull()
  })
})
