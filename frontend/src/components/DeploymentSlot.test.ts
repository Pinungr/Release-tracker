import { expect, it } from 'vitest'
import { edgeFor } from './DeploymentSlot'
import type { SlotView } from '../types'

it('distinguishes available, booked, frozen, holiday and completed rows', () => {
  const slot = { bookable: true, state: 'AVAILABLE', booking: null } as SlotView
  expect(edgeFor(slot, false, false)).toContain('bg-emerald-50')
  const booked = { ...slot, bookable: false, booking: { status: 'BOOKED', is_locked: false } } as SlotView
  expect(edgeFor(booked, false, false)).toContain('bg-blue-50')
  expect(edgeFor({ ...booked, manually_frozen: true }, false, false)).toContain('bg-slate-100')
  expect(edgeFor(booked, true, false)).toContain('bg-amber-50')
  expect(edgeFor({ ...booked, booking: { ...booked.booking!, status: 'COMPLETED' } }, false, false)).toContain('bg-violet-50')
})
