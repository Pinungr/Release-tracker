import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { DocumentTypeConfig } from '../types'
import { CheckboxField, TextField } from './FormControls'
import { Alert, Check, ChevronLeft, ChevronRight, Cross, Document, Pencil, Plus, Shield, Spinner, Trash } from './Icons'
import { ConfirmationModal } from './Modal'
import { useToast } from './ToastNotification'

const EMPTY_DRAFT = { label: '', description: '', is_required: false, allow_multiple: false }

export function DocumentSettings({ onChanged }: { onChanged: () => void }) {
  const toast = useToast()
  const [data, setData] = useState<DocumentTypeConfig[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | 'new' | null>(null)
  const saving = useRef(false)
  const [editing, setEditing] = useState<{ id: number; label: string; description: string } | null>(null)
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState(EMPTY_DRAFT)
  const [pendingDelete, setPendingDelete] = useState<DocumentTypeConfig | null>(null)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let active = true
    setError(null)
    api.getDocumentTypes().then((result) => { if (active) setData(result) })
      .catch((caught) => { if (active) setError(caught instanceof ApiError ? caught.message : 'Could not load document types.') })
    return () => { active = false }
  }, [reload])

  async function run(id: number | 'new', action: () => Promise<DocumentTypeConfig[]>, message: string) {
    if (saving.current) return false
    saving.current = true
    setBusyId(id)
    try {
      setData(await action())
      onChanged()
      toast.success(message)
      return true
    } catch (caught) {
      toast.error('Could not save', caught instanceof ApiError ? caught.message : 'Please try again.')
      return false
    } finally {
      saving.current = false
      setBusyId(null)
    }
  }

  function move(index: number, offset: number) {
    if (!data) return
    const ids = data.map((type) => type.id)
    const [moved] = ids.splice(index, 1)
    ids.splice(index + offset, 0, moved)
    void run(moved, () => api.reorderDocumentTypes(ids), 'Document order updated.')
  }

  const disabled = busyId !== null
  const activeCount = data?.filter((type) => type.is_active).length ?? 0
  const requiredCount = data?.filter((type) => type.is_active && type.is_required).length ?? 0
  const fileCount = data?.reduce((count, type) => count + type.file_count, 0) ?? 0

  return (
    <section aria-labelledby="document-settings-title" className="space-y-5">
      <div className="overflow-hidden rounded-2xl border border-slate-200 shadow-sm">
        <div className="relative overflow-hidden bg-slate-900 px-5 py-4 sm:px-6">
          <div aria-hidden="true" className="pointer-events-none absolute -right-10 -top-16 size-56 rounded-full border-[28px] border-white/5" />
          <div className="relative flex items-start gap-4">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-white/10 ring-1 ring-white/15"><Document className="size-5 text-indigo-200" /></div>
            <div className="min-w-0">
              <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-indigo-200">Release readiness</p>
              <h3 id="document-settings-title" className="mt-1 text-lg font-semibold tracking-tight text-white">Document uploads</h3>
              <p className="mt-1.5 max-w-lg text-xs leading-5 text-slate-300">Define the evidence every deployment needs. Clear requirements, ready releases.</p>
            </div>
          </div>
        </div>
        <dl className="grid grid-cols-3 divide-x divide-slate-200 bg-slate-50/80 py-3">
          {[['Active types', activeCount], ['Required types', requiredCount], ['Uploaded files', fileCount]].map(([label, count]) => (
            <div key={label} className="px-3 sm:px-6"><dd className="text-xl font-semibold tracking-tight text-slate-900">{data ? count : '—'}</dd><dt className="mt-0.5 text-[11px] font-medium text-slate-500 sm:text-xs">{label}</dt></div>
          ))}
        </dl>
      </div>

      {error ? <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700"><p>{error}</p><button type="button" className="btn-secondary btn-sm" onClick={() => setReload((value) => value + 1)}>Retry</button></div> : null}
      {!data && !error ? <div role="status" className="flex items-center justify-center gap-2 py-10 text-sm text-ink-muted"><Spinner className="size-4" />Loading document types…</div> : null}

      {data ? <>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><h4 className="text-sm font-semibold text-ink">Upload requirements <span className="ml-1 text-ink-muted">{data.length}</span></h4><p className="mt-1 text-xs text-ink-muted">Shown to schedulers in the order below.</p></div>
          <button type="button" className="btn-primary btn-sm" disabled={disabled || adding} onClick={() => setAdding(true)}><Plus className="size-4" />Add document type</button>
        </div>

        {adding ? <form aria-label="Add a document type" className="rounded-xl border border-brand-100 bg-brand-50/50 p-4 sm:p-5" onSubmit={(event) => {
          event.preventDefault()
          if (!draft.label.trim()) return
          void run('new', () => api.createDocumentType({ ...draft, label: draft.label.trim(), description: draft.description.trim() || null }), 'Document type added.').then((ok) => {
            if (ok) { setDraft(EMPTY_DRAFT); setAdding(false) }
          })
        }}>
          <div className="mb-4 flex items-center justify-between"><h4 className="text-sm font-semibold text-brand-700">New document type</h4><button type="button" className="btn-ghost p-1.5" aria-label="Close new document type" disabled={disabled} onClick={() => setAdding(false)}><Cross className="size-4" /></button></div>
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField label="Name" name="new-document-type" required value={draft.label} onChange={(value) => setDraft({ ...draft, label: value })} maxLength={120} placeholder="e.g. Security approval" disabled={disabled} />
            <TextField label="Description" name="new-document-description" value={draft.description} onChange={(value) => setDraft({ ...draft, description: value })} placeholder="Guidance for your team (optional)" maxLength={1000} disabled={disabled} />
          </div>
          <div className="mt-4 flex flex-wrap gap-x-6 gap-y-3"><CheckboxField label="Required before booking" name="new-document-required" checked={draft.is_required} onChange={(value) => setDraft({ ...draft, is_required: value })} /><CheckboxField label="Allow multiple files" name="new-document-multiple" checked={draft.allow_multiple} onChange={(value) => setDraft({ ...draft, allow_multiple: value })} /></div>
          <div className="mt-5 flex justify-end gap-2"><button type="button" className="btn-ghost btn-sm" disabled={disabled} onClick={() => setAdding(false)}>Cancel</button><button type="submit" className="btn-primary btn-sm" disabled={disabled || !draft.label.trim()}>{busyId === 'new' ? <Spinner className="size-4" /> : <Plus className="size-4" />}Create document type</button></div>
        </form> : null}

        {data.length === 0 ? <div className="rounded-xl border border-dashed border-line px-5 py-10 text-center"><Document className="mx-auto size-8 text-slate-400" /><p className="mt-3 text-sm font-semibold text-ink">Start your document checklist</p><p className="mt-1 text-sm text-ink-muted">Add the evidence your team should upload with each deployment.</p></div> : null}

        <ol className="grid items-start gap-3 sm:grid-cols-2">
          {data.map((type, index) => <li key={type.id} className={`overflow-hidden rounded-xl border transition-colors ${type.is_active ? 'border-slate-200 bg-white shadow-sm' : 'border-dashed border-slate-300 bg-slate-50'}`}>
            <div className="p-4">
              <div className="flex items-start gap-3">
                <div className={`flex size-10 shrink-0 items-center justify-center rounded-xl ${type.is_active ? 'bg-indigo-50 text-indigo-600' : 'bg-slate-200/60 text-slate-400'}`}><Document className="size-5" /></div>
                <div className="min-w-0 flex-1"><h5 className="break-words text-sm font-semibold leading-5 text-ink">{type.label}</h5><p className="mt-1 text-xs leading-5 text-ink-muted">{type.description || (type.is_required ? 'Evidence required before a deployment can be booked.' : 'Additional evidence for your deployment.')}</p></div>
                <button type="button" role="switch" aria-checked={type.is_active} aria-label={`${type.label} enabled`} disabled={disabled} title={type.is_active ? 'Disable new uploads' : 'Enable new uploads'} onClick={() => void run(type.id, () => api.updateDocumentType(type.id, { is_active: !type.is_active }), type.is_active ? 'Document type disabled.' : 'Document type enabled.')} className="flex shrink-0 items-center gap-2 rounded-lg p-1 disabled:opacity-50">
                  <span className={`relative h-5 w-9 rounded-full transition-colors ${type.is_active ? 'bg-brand-600' : 'bg-slate-300'}`}><span className={`absolute left-0.5 top-0.5 size-4 rounded-full bg-white shadow-sm transition-transform ${type.is_active ? 'translate-x-4' : 'translate-x-0'}`} /></span>
                </button>
              </div>

              {editing?.id === type.id ? <form aria-label={`Edit ${type.label}`} className="mt-4 grid gap-3 rounded-lg bg-slate-50 p-3" onSubmit={(event) => {
                event.preventDefault()
                if (!editing.label.trim()) return
                void run(type.id, () => api.updateDocumentType(type.id, { label: editing.label.trim(), description: editing.description.trim() || null }), 'Document type updated.').then((ok) => { if (ok) setEditing(null) })
              }}>
                <TextField label="Name" name={`document-name-${type.id}`} required value={editing.label} onChange={(label) => setEditing({ ...editing, label })} maxLength={120} disabled={disabled} />
                <TextField label="Description" name={`document-description-${type.id}`} value={editing.description} onChange={(description) => setEditing({ ...editing, description })} maxLength={1000} disabled={disabled} />
                <div className="flex justify-end gap-2"><button type="button" className="btn-ghost btn-sm" disabled={disabled} onClick={() => setEditing(null)}>Cancel</button><button type="submit" className="btn-primary btn-sm" disabled={disabled || !editing.label.trim()}><Check className="size-3.5" />Save changes</button></div>
              </form> : null}

              <div className="mt-4 grid grid-cols-2 gap-3">
                <label className="min-w-0"><span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wider text-ink-muted">Requirement</span><select className="field py-1.5 text-xs" aria-label={`${type.label} requirement`} value={type.is_required ? 'required' : 'optional'} disabled={disabled} onChange={(event) => void run(type.id, () => api.updateDocumentType(type.id, { is_required: event.target.value === 'required' }), 'Requirement updated.')}><option value="required">Required</option><option value="optional">Optional</option></select></label>
                <label className="min-w-0"><span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wider text-ink-muted">Upload mode</span><select className="field py-1.5 text-xs" aria-label={`${type.label} file mode`} value={type.allow_multiple ? 'multiple' : 'single'} disabled={disabled} onChange={(event) => void run(type.id, () => api.updateDocumentType(type.id, { allow_multiple: event.target.value === 'multiple' }), 'File mode updated.')}><option value="single">Single file</option><option value="multiple">Multiple files</option></select></label>
              </div>

              {!type.allow_multiple && (type.multi_file_schedules ?? 0) > 0 ? <p className="mt-3 flex items-start gap-2 rounded-lg bg-amber-50 p-2.5 text-xs leading-5 text-amber-800"><Alert className="mt-0.5 size-3.5 shrink-0" /><span>{type.multi_file_schedules} schedule{type.multi_file_schedules === 1 ? '' : 's'} retain existing multiple files. Their next upload replaces those files with one.</span></p> : null}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 bg-slate-50/70 px-4 py-2">
              <span className="text-xs text-ink-muted">{busyId === type.id ? <span role="status" className="flex items-center gap-1.5"><Spinner className="size-3.5" />Saving…</span> : <><span className="font-semibold text-ink">{type.file_count}</span> uploaded file{type.file_count === 1 ? '' : 's'}</>}</span>
              <div className="flex items-center gap-1">
                <span className="mr-1 text-[10px] font-medium tabular-nums text-slate-400">{String(index + 1).padStart(2, '0')}</span>
                <button type="button" className="btn-ghost rounded-md p-1.5 disabled:opacity-25" aria-label={`Move ${type.label} up`} title="Move up" disabled={disabled || index === 0} onClick={() => move(index, -1)}><ChevronLeft className="size-3.5 rotate-90" /></button>
                <button type="button" className="btn-ghost rounded-md p-1.5 disabled:opacity-25" aria-label={`Move ${type.label} down`} title="Move down" disabled={disabled || index === data.length - 1} onClick={() => move(index, 1)}><ChevronRight className="size-3.5 rotate-90" /></button>
                <span aria-hidden="true" className="mx-1 h-4 w-px bg-slate-200" />
                <button type="button" className="btn-ghost rounded-md p-1.5" aria-label={`Edit ${type.label}`} title="Edit name and description" disabled={disabled} onClick={() => setEditing({ id: type.id, label: type.label, description: type.description || '' })}><Pencil className="size-3.5" /></button>
                {type.file_count === 0 ? <button type="button" className="btn-ghost rounded-md p-1.5 text-rose-500 hover:bg-rose-50 hover:text-rose-600" aria-label={`Delete ${type.label}`} title="Delete unused document type" disabled={disabled} onClick={() => setPendingDelete(type)}><Trash className="size-3.5" /></button> : null}
              </div>
            </div>
          </li>)}
        </ol>

        <div className="flex items-start gap-3 rounded-xl border border-indigo-100 bg-indigo-50/50 p-4"><Shield className="mt-0.5 size-4 shrink-0 text-indigo-500" /><div className="text-xs leading-5 text-slate-600"><p className="font-semibold text-slate-800">Existing documents stay protected</p><p className="mt-1">Disabling a type hides it from new uploads. Required types must keep at least one file. Switching to single file preserves existing uploads until the next replacement.</p></div></div>
      </> : null}

      <ConfirmationModal open={pendingDelete !== null} onClose={() => { if (!disabled) setPendingDelete(null) }} title="Delete document type?" description={`Remove “${pendingDelete?.label ?? ''}” from your upload configuration.`} note="This type has no uploaded files. You can disable it instead to keep it for later." confirmLabel="Delete document type" cancelLabel="Keep document type" busy={disabled} onConfirm={() => {
        if (pendingDelete) void run(pendingDelete.id, () => api.deleteDocumentType(pendingDelete.id), 'Document type deleted.').then((ok) => { if (ok) setPendingDelete(null) })
      }} />
    </section>
  )
}
