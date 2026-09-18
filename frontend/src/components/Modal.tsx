import { useEffect, type ReactNode } from 'react'
import { Cross } from './Icons'

interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  description?: ReactNode
  icon?: ReactNode
  children: ReactNode
  footer?: ReactNode
  size?: 'sm' | 'md'
}

export function Modal({
  open,
  onClose,
  title,
  description,
  icon,
  children,
  footer,
  size = 'sm',
}: ModalProps) {
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[60] flex items-end justify-center p-3 sm:items-center sm:p-6">
      <div
        className="animate-fade-in absolute inset-0 bg-ink/40 backdrop-blur-[2px]"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`animate-fade-in relative w-full ${size === 'sm' ? 'sm:max-w-md' : 'sm:max-w-lg'} card overflow-hidden shadow-raised`}
      >
        <div className="flex items-start gap-3 px-5 pt-5">
          {icon ? <span className="mt-0.5 shrink-0">{icon}</span> : null}
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold text-ink">{title}</h2>
            {description ? (
              <div className="mt-1 text-sm text-ink-muted">{description}</div>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="btn-ghost -mt-1.5 -mr-1.5 shrink-0 rounded-lg p-1.5"
            aria-label="Close dialog"
          >
            <Cross className="size-4" />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer ? <div className="border-t border-line bg-canvas/70 px-5 py-3.5">{footer}</div> : null}
      </div>
    </div>
  )
}

interface ConfirmationModalProps {
  open: boolean
  onClose: () => void
  onConfirm: () => void
  title: string
  description?: ReactNode
  facts?: { label: string; value: ReactNode }[]
  note?: string
  confirmLabel: string
  cancelLabel?: string
  busy?: boolean
  destructive?: boolean
  children?: ReactNode
}

export function ConfirmationModal({
  open,
  onClose,
  onConfirm,
  title,
  description,
  facts = [],
  note,
  confirmLabel,
  cancelLabel = 'Keep booking',
  busy = false,
  destructive = true,
  children,
}: ConfirmationModalProps) {
  return (
    <Modal open={open} onClose={onClose} title={title} description={description}>
      {facts.length > 0 ? (
        <dl className="mb-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 rounded-lg bg-canvas p-3 text-sm">
          {facts.map((fact) => (
            <div key={fact.label} className="col-span-2 grid grid-cols-subgrid">
              <dt className="text-ink-muted">{fact.label}</dt>
              <dd className="font-medium text-ink">{fact.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {note ? <p className="mb-4 text-sm text-ink-muted">{note}</p> : null}
      {children}
      <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <button type="button" className="btn-secondary" onClick={onClose} disabled={busy}>
          {cancelLabel}
        </button>
        <button
          type="button"
          className={destructive ? 'btn-danger' : 'btn-primary'}
          onClick={onConfirm}
          disabled={busy}
        >
          {confirmLabel}
        </button>
      </div>
    </Modal>
  )
}
