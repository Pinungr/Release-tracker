import { useCallback, useRef, useState } from 'react'
import type { BookingDetail, FilterKey } from '../types'

export interface BoardView {
  filter: FilterKey
  query: string
}

/**
 * Cloning narrows the board to free slots so the user can pick a destination.
 * Ending the clone — cancelled, saved or dismissed — restores whatever the
 * board showed beforehand. Without that, every existing booking stays hidden
 * behind the "Available" filter for the rest of the session, and tenants lose
 * sight of how busy the RM team already is.
 */
export function useCloneMode(view: BoardView, setView: (next: BoardView) => void) {
  const [cloneSource, setCloneSource] = useState<BookingDetail | null>(null)
  const before = useRef<BoardView | null>(null)

  const startClone = useCallback(
    (source: BookingDetail) => {
      // Record the view only once, so cloning again mid-clone still restores
      // the board the user had before the first clone.
      if (!before.current) before.current = view
      setCloneSource(source)
      setView({ filter: 'AVAILABLE', query: '' })
    },
    [view, setView],
  )

  const endClone = useCallback(() => {
    setCloneSource(null)
    const previous = before.current
    if (!previous) return
    before.current = null
    setView(previous)
  }, [setView])

  return { cloneSource, startClone, endClone }
}
