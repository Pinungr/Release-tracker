import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { BookingDrawer } from './BookingDrawer'
import { valuesForClone } from './BookingForm'
import { ToastProvider } from './ToastNotification'
import type { BookingDetail, DayView, SlotView, PublicSettings } from '../types'
import { api } from '../services/api'
vi.mock('../services/api', () => ({ api: { getActiveTenants: vi.fn().mockResolvedValue([{id:1,name:'Tenant',is_active:true}]), createBooking: vi.fn() }, ApiError: class extends Error {} }))
afterEach(cleanup)
const source = { id: 12, booking_reference:'PDS-20260920-001',tenant_id:1,technology:'Application', verifier_name:'Verifier',verifier_email:'v@example.com',git_repository:'https://example.com/repo',implementation_summary:'Deploy the new application',deployment_description:'Deployment instructions',justification:'Repeat release',impacted_region:'APAC',jira_number:'OLD-123',jira_url:'https://example.com/OLD-123',additional_comments:'Do not copy',emergency_approval_reference:'OLD APPROVAL',status:'COMPLETED',attachments:[{id:1}],change_number:'OLD-CHANGE' } as BookingDetail
it('prefills only reusable fields and keeps Jira/comments/approvals empty', () => {
 const values = valuesForClone(source)
 expect(values.implementation_summary).toBe(source.implementation_summary)
 expect(values.tenant_id).toBe('1')
 expect(values.jira_number).toBe('')
 expect(values.additional_comments).toBe('')
 expect(values.emergency_approval_reference).toBe('')
 expect(values).not.toHaveProperty('change_number')
 expect(values).not.toHaveProperty('attachments')
})
it('requires fresh documents even when the source has documents', async () => {
 const settings = {jira_required_at_booking:false, max_file_size_mb:20,technologies:['Application'],document_catalog:[{category:'IMPLEMENTATION_PLAN', label:'Implementation plan',required:true,multiple:false}]} as PublicSettings
 render(<ToastProvider><BookingDrawer open onClose={vi.fn()} settings={settings} isAdmin={false} editBooking={null} cloneSource={source} onSaved={vi.fn()} createTarget={{day:{day:'2026-10-04',weekday:'Sunday',date_label:'4 October'} as DayView,slot:{slot_number:1,name:'Slot 1',time_label:'9 PM–5 AM'} as SlotView,isEmergency:false}} /></ToastProvider>)
 await waitFor(() => expect(api.getActiveTenants).toHaveBeenCalled())
 fireEvent.click(screen.getByRole('button',{name:'Confirm booking'}))
 expect(await screen.findByText('Implementation plan is required before booking the slot.')).toBeTruthy()
 expect(api.createBooking).not.toHaveBeenCalled()
})
