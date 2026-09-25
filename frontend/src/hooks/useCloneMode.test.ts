import { act, renderHook } from '@testing-library/react'
import { useState } from 'react'
import { expect, it } from 'vitest'
import type { BookingDetail } from '../types'
import { type BoardView, useCloneMode } from './useCloneMode'

const source = { id: 12, booking_reference: 'PDS-20260920-001' } as BookingDetail

/** Wires the hook to real state, the way App does. */
function useBoard(initial: BoardView) {
  const [view, setView] = useState<BoardView>(initial)
  return { view, ...useCloneMode(view, setView) }
}

it('narrows the board to free slots while cloning', () => {
  const { result } = renderHook(() => useBoard({ filter: 'ALL', query: '' }))
  act(() => result.current.startClone(source))
  expect(result.current.cloneSource).toBe(source)
  expect(result.current.view).toEqual({ filter: 'AVAILABLE', query: '' })
})

it('shows existing bookings again once the clone ends', () => {
  const { result } = renderHook(() => useBoard({ filter: 'ALL', query: '' }))
  act(() => result.current.startClone(source))
  act(() => result.current.endClone())
  expect(result.current.cloneSource).toBeNull()
  // Regression: this used to stay on AVAILABLE, hiding every booked slot for
  // the rest of the session.
  expect(result.current.view.filter).toBe('ALL')
})

it('restores the exact filter and search the user had before cloning', () => {
  const { result } = renderHook(() => useBoard({ filter: 'TECH:Databricks', query: 'EPCAT' }))
  act(() => result.current.startClone(source))
  act(() => result.current.endClone())
  expect(result.current.view).toEqual({ filter: 'TECH:Databricks', query: 'EPCAT' })
})

it('restores the pre-clone view even if a second clone starts mid-clone', () => {
  const { result } = renderHook(() => useBoard({ filter: 'MINE', query: '' }))
  act(() => result.current.startClone(source))
  act(() => result.current.startClone({ ...source, id: 13 } as BookingDetail))
  act(() => result.current.endClone())
  expect(result.current.view.filter).toBe('MINE')
})

it('leaves the board alone when a drawer closes with no clone in progress', () => {
  const { result } = renderHook(() => useBoard({ filter: 'BOOKED', query: 'x' }))
  act(() => result.current.endClone())
  expect(result.current.view).toEqual({ filter: 'BOOKED', query: 'x' })
})
