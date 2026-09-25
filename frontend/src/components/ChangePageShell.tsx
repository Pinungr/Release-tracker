import type { ReactNode } from 'react'

export function ChangePageShell({ open, onClose, title, eyebrow, subtitle, footer, children }: {
  open: boolean; onClose: () => void; title: string; eyebrow?: ReactNode;
  subtitle?: ReactNode; footer?: ReactNode; children: ReactNode; width?: string
}) {
  if (!open) return null
  return <main className="mx-auto w-full max-w-[88rem] flex-1 space-y-5 px-4 py-6 sm:px-6 lg:px-8">
    <button className="btn-secondary" onClick={onClose}>← Back to calendar</button>
    <header className="card space-y-3 p-5 sm:p-6">
      <div className="text-xs font-bold uppercase tracking-wide text-ink-muted">Change details</div>
      {eyebrow}<h1 className="text-2xl font-bold text-ink">{title}</h1>
      <div className="text-sm text-ink-muted">{subtitle}</div>
      <div className="border-t border-line pt-4">{footer}</div>
    </header>
    {children}
  </main>
}
