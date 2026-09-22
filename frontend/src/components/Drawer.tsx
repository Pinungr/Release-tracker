import { useEffect, useRef, type ReactNode } from 'react'
import { lockBodyScroll } from '../utils/scrollLock'
import { Cross } from './Icons'

interface DrawerProps {
  open: boolean
  onClose: () => void
  title: string
  subtitle?: ReactNode
  eyebrow?: ReactNode
  width?: 'md' | 'lg' | 'xl'
  footer?: ReactNode
  children: ReactNode
}

const WIDTHS = {
  md: 'sm:max-w-md',
  lg: 'sm:max-w-xl',
  xl: 'sm:max-w-3xl',
} as const

/**
 * Right-side drawer used for booking, details and admin controls so the app
 * never navigates away from the weekly board.
 */
export function Drawer({
  open,
  onClose,
  title,
  subtitle,
  eyebrow,
  width = 'lg',
  footer,
  children,
}: DrawerProps) {
  const panel = useRef<HTMLDivElement>(null)

  // Kept in a ref so the effect below depends only on `open`. Callers pass an
  // inline arrow, which changes identity on every render; without this the
  // lock/unlock pair would thrash on each parent re-render.
  const closeRef = useRef(onClose)
  closeRef.current = onClose

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeRef.current()
    }
    document.addEventListener('keydown', onKey)
    const releaseScroll = lockBodyScroll()
    panel.current?.focus()
    return () => {
      document.removeEventListener('keydown', onKey)
      releaseScroll()
    }
  }, [open])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="animate-fade-in absolute inset-0 bg-ink/35 backdrop-blur-[2px]"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`animate-drawer-in relative flex h-full w-full flex-col bg-surface shadow-drawer outline-none ${WIDTHS[width]}`}
      >
        <header className="flex items-start gap-3 border-b border-line px-5 py-4 sm:px-6">
          <div className="min-w-0 flex-1">
            {eyebrow ? <div className="mb-1.5">{eyebrow}</div> : null}
            <h2 className="truncate text-lg font-semibold text-ink">{title}</h2>
            {subtitle ? <div className="mt-0.5 text-sm text-ink-muted">{subtitle}</div> : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="btn-ghost -mt-1 shrink-0 rounded-lg p-2"
            aria-label="Close panel"
          >
            <Cross className="size-5" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6">{children}</div>

        {footer ? (
          <footer className="border-t border-line bg-canvas/70 px-5 py-3.5 sm:px-6">{footer}</footer>
        ) : null}
      </div>
    </div>
  )
}
