/**
 * Reference-counted body scroll lock.
 *
 * Overlays stack: opening a booking drawer and then the edit drawer (or an
 * admin drawer) means two locks are held at once. A naive
 * save-previous/restore-previous in each overlay does not compose — the inner
 * one captures the outer one's `hidden` and restores it on close, leaving the
 * page permanently unscrollable with nothing open.
 *
 * Only the first lock records the original value and only the last release
 * restores it, so any open/close order ends up correct.
 */
let locks = 0
let previousOverflow = ''

export function lockBodyScroll(): () => void {
  if (locks === 0) {
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  }
  locks += 1

  let released = false
  return function release() {
    // Guard against a double release (React 18 can re-run effect cleanups),
    // which would otherwise drop the count below the number of open overlays.
    if (released) return
    released = true
    locks -= 1
    if (locks <= 0) {
      locks = 0
      document.body.style.overflow = previousOverflow
    }
  }
}
