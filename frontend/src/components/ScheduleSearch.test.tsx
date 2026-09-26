import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { ScheduleSearch } from './ScheduleSearch'
import { api } from '../services/api'
vi.mock('../services/api', () => ({ api: { searchSchedules: vi.fn().mockResolvedValue([{id:4,booking_reference:'pds-001',tenant_name:'Tenant',deployment_date:'2026-01-01',status:'COMPLETED',change_number:'CHG-1'}]) }, ApiError: class extends Error {} }))
afterEach(cleanup)
it('opens a completed schedule returned by global number search', async () => {
 const onOpen=vi.fn()
 render(<ScheduleSearch onOpen={onOpen} />)
 fireEvent.change(screen.getByRole('textbox'),{target:{value:'pds-001'}})
 fireEvent.click(screen.getByRole('button',{name:'Find schedule'}))
 await waitFor(()=>expect(api.searchSchedules).toHaveBeenCalledWith('pds-001',undefined))
 fireEvent.click(await screen.findByRole('button',{name:/pds-001.*Tenant/}))
 expect(onOpen).toHaveBeenCalledWith(4, 'pds-001')
 expect(screen.queryByText('COMPLETED')).toBeNull()
})
