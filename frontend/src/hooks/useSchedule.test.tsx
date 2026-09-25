import { act, renderHook, waitFor, cleanup } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useSchedule } from './useSchedule'
import { api } from '../services/api'
import type { Schedule } from '../types'

vi.mock('../services/api', () => ({ api: { getSchedule: vi.fn() }, ApiError: class extends Error {} }))
afterEach(cleanup)
it('finds availability once, keeps refresh on that week, and allows previous-week navigation', async () => {
  vi.mocked(api.getSchedule).mockResolvedValue({ week_start: '2026-10-04' } as Schedule)
  const { result, rerender } = renderHook(({ anchor }) => useSchedule(anchor), { initialProps: { anchor: '' } })
  await waitFor(() => expect(result.current.loading).toBe(false))
  expect(api.getSchedule).toHaveBeenLastCalledWith(expect.any(String), true)
  act(() => result.current.refresh())
  await waitFor(() => expect(result.current.loading).toBe(false))
  expect(api.getSchedule).toHaveBeenLastCalledWith('2026-10-04', false)
  rerender({ anchor: '2026-09-27' })
  await waitFor(() => expect(result.current.loading).toBe(false))
  expect(api.getSchedule).toHaveBeenLastCalledWith('2026-09-27', false)
})
