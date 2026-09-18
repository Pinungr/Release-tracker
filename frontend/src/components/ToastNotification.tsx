import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { Alert, Check, Cross, Lock } from './Icons'

type ToastKind = 'success' | 'error' | 'info' | 'locked'

interface Toast {
  id: number
  kind: ToastKind
  title: string
  body?: string
}

interface ToastApi {
  success: (title: string, body?: string) => void
  error: (title: string, body?: string) => void
  info: (title: string, body?: string) => void
  locked: (title: string, body?: string) => void
}

const ToastContext = createContext<ToastApi | null>(null)

const STYLES: Record<ToastKind, { ring: string; icon: ReactNode }> = {
  success: {
    ring: 'border-emerald-200 bg-emerald-50',
    icon: <Check className="size-5 text-emerald-600" />,
  },
  error: { ring: 'border-rose-200 bg-rose-50', icon: <Alert className="size-5 text-rose-600" /> },
  info: { ring: 'border-brand-100 bg-brand-50', icon: <Alert className="size-5 text-brand-600" /> },
  locked: { ring: 'border-slate-200 bg-slate-50', icon: <Lock className="size-5 text-slate-600" /> },
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
  }, [])

  const push = useCallback(
    (kind: ToastKind, title: string, body?: string) => {
      const id = Date.now() + Math.random()
      setToasts((current) => [...current.slice(-3), { id, kind, title, body }])
      window.setTimeout(() => dismiss(id), kind === 'error' || kind === 'locked' ? 8000 : 5000)
    },
    [dismiss],
  )

  const api = useMemo<ToastApi>(
    () => ({
      success: (title, body) => push('success', title, body),
      error: (title, body) => push('error', title, body),
      info: (title, body) => push('info', title, body),
      locked: (title, body) => push('locked', title, body),
    }),
    [push],
  )

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        className="pointer-events-none fixed inset-x-3 bottom-3 z-[70] flex flex-col items-center gap-2 sm:inset-x-auto sm:right-5 sm:bottom-5 sm:items-end"
        role="status"
        aria-live="polite"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`animate-toast-in pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-xl border p-3.5 shadow-raised ${STYLES[toast.kind].ring}`}
          >
            <span className="mt-0.5 shrink-0">{STYLES[toast.kind].icon}</span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-ink">{toast.title}</p>
              {toast.body ? (
                <p className="mt-0.5 text-xs whitespace-pre-line text-ink-muted">{toast.body}</p>
              ) : null}
            </div>
            <button
              type="button"
              onClick={() => dismiss(toast.id)}
              className="rounded p-0.5 text-ink-muted transition-colors hover:text-ink"
              aria-label="Dismiss notification"
            >
              <Cross className="size-4" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastApi {
  const context = useContext(ToastContext)
  if (!context) throw new Error('useToast must be used inside <ToastProvider>')
  return context
}
