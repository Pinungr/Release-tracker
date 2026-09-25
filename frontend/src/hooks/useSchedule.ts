import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { Schedule } from '../types'

/**
 * Loads exactly one week at a time. Week navigation refetches; no historical
 * bookings are pulled on start-up.
 */
export function useSchedule(anchor: string) {
  const resolvedWeek = useRef('')
  const [schedule, setSchedule] = useState<Schedule | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(
    async (signal?: AbortSignal, initial = false) => {
      setLoading(true)
      try {
        const result = await api.getSchedule(anchor || resolvedWeek.current || new Date().toISOString().slice(0, 10), anchor === '' && initial)
        if (!signal?.aborted) {
          resolvedWeek.current = result.week_start
          setSchedule(result)
          setError(null)
        }
      } catch (caught) {
        if (!signal?.aborted) {
          setError(caught instanceof ApiError ? caught.message : 'Could not load the schedule.')
        }
      } finally {
        if (!signal?.aborted) setLoading(false)
      }
    },
    [anchor],
  )

  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal, true)
    return () => controller.abort()
  }, [load])

  return { schedule, loading, error, refresh: () => void load() }
}
