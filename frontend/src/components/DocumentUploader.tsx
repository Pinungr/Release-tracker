import { useRef, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { Attachment, BookingDetail, DocumentCategory, PublicSettings } from '../types'
import { formatTimestamp } from '../utils/dates'
import { formatBytes } from '../utils/format'
import { Document, Download, Spinner, Trash, Upload } from './Icons'
import { ConfirmationModal } from './Modal'
import { useToast } from './ToastNotification'

const ALLOWED = [
  '.pdf',
  '.doc',
  '.docx',
  '.xls',
  '.xlsx',
  '.csv',
  '.txt',
  '.zip',
  '.sql',
  '.png',
  '.jpg',
  '.jpeg',
]

interface DocumentUploaderProps {
  booking: BookingDetail
  settings: PublicSettings
  timezone?: string
  readOnly?: boolean
  onUpdated: (booking: BookingDetail) => void
}

interface PendingDelete {
  ids: number[]
  names: string[]
}

/**
 * Manage Attachments: upload, replace, download and delete deployment documents.
 *
 * What the caller may do comes from booking.can_manage_attachments, which the
 * backend derives from the same rules it enforces on every upload/delete.
 */
export function DocumentUploader({
  booking,
  settings,
  timezone = 'UTC',
  readOnly = false,
  onUpdated,
}: DocumentUploaderProps) {
  const toast = useToast()
  const [busy, setBusy] = useState<DocumentCategory | null>(null)
  const [downloading, setDownloading] = useState<number | null>(null)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null)
  const [deleting, setDeleting] = useState(false)
  const inputs = useRef<Partial<Record<DocumentCategory, HTMLInputElement | null>>>({})
  const canManage = !readOnly && booking.can_manage_attachments

  const activeKeys = new Set(settings.document_catalog.map((entry) => entry.category))
  const retired = booking.attachments.filter((a) => !activeKeys.has(a.category))

  function rejectFiles(files: File[]): string | null {
    for (const file of files) {
      const extension = `.${file.name.split('.').pop()?.toLowerCase() ?? ''}`
      if (!ALLOWED.includes(extension)) return `${file.name}: allowed formats are ${ALLOWED.join(', ')}`
      if (file.size === 0) return `${file.name} is empty.`
      if (file.size > settings.max_file_size_mb * 1024 * 1024) {
        return `${file.name} is ${formatBytes(file.size)}; the limit is ${settings.max_file_size_mb} MB.`
      }
    }
    return null
  }

  async function upload(category: DocumentCategory, files: File[]) {
    const problem = rejectFiles(files)
    if (problem) {
      toast.error('File not accepted', problem)
      return
    }
    setBusy(category)
    try {
      const updated = await api.uploadAttachments(booking.id, category, files)
      onUpdated(updated)
      toast.success(files.length > 1 ? `${files.length} documents uploaded` : 'Document uploaded', files.map((f) => f.name).join(', '))
    } catch (error) {
      toast.error('Upload failed', error instanceof ApiError ? error.message : 'Please try again.')
    } finally {
      setBusy(null)
    }
  }

  async function downloadFile(attachmentId: number, name: string) {
    setDownloading(attachmentId)
    try {
      await api.downloadAttachment(booking.id, attachmentId, name)
    } catch (error) {
      toast.error('Download failed', error instanceof ApiError ? error.message : 'Please try again.')
    } finally {
      setDownloading(null)
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return
    setDeleting(true)
    try {
      const updated = pendingDelete.ids.length === 1
        ? await api.deleteAttachment(booking.id, pendingDelete.ids[0])
        : await api.deleteAttachments(booking.id, pendingDelete.ids)
      onUpdated(updated)
      setSelected((current) => new Set([...current].filter((id) => !pendingDelete.ids.includes(id))))
      toast.success(pendingDelete.ids.length === 1 ? 'Document removed' : `${pendingDelete.ids.length} documents removed`, pendingDelete.names.join(', '))
      setPendingDelete(null)
    } catch (error) {
      toast.error('Could not remove the documents', error instanceof ApiError ? error.message : '')
    } finally {
      setDeleting(false)
    }
  }

  function toggle(id: number, on: boolean) {
    setSelected((current) => {
      const next = new Set(current)
      if (on) next.add(id)
      else next.delete(id)
      return next
    })
  }

  function fileRow(file: Attachment, options: { selectable: boolean; deletable: boolean; lockedReason?: string }) {
    return (
      <li key={file.id} className="flex items-center gap-2 rounded-md bg-canvas px-2.5 py-1.5 text-xs">
        {options.selectable ? (
          <input
            type="checkbox"
            aria-label={`Select ${file.original_filename}`}
            checked={selected.has(file.id)}
            onChange={(event) => toggle(file.id, event.target.checked)}
          />
        ) : null}
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium text-ink">{file.original_filename}</span>
          <span className="block truncate text-ink-muted">
            {formatBytes(file.size_bytes)}
            {file.uploaded_by ? ` · ${file.uploaded_by}` : ''}
            {` · ${formatTimestamp(file.uploaded_at, timezone)}`}
          </span>
        </span>
        {booking.can_download_attachments ? (
          <button
            type="button"
            onClick={() => void downloadFile(file.id, file.original_filename)}
            className="btn-ghost btn-sm shrink-0 px-1.5"
            aria-label={`Download ${file.original_filename}`}
            disabled={downloading === file.id}
          >
            {downloading === file.id ? <Spinner className="size-3.5" /> : <Download className="size-3.5" />}
          </button>
        ) : null}
        {canManage ? (
          <button
            type="button"
            onClick={() => setPendingDelete({ ids: [file.id], names: [file.original_filename] })}
            className="btn-ghost btn-sm shrink-0 px-1.5 text-rose-600 hover:bg-rose-50 disabled:opacity-40"
            aria-label={`Remove ${file.original_filename}`}
            disabled={!options.deletable}
            title={options.deletable ? undefined : options.lockedReason}
          >
            <Trash className="size-3.5" />
          </button>
        ) : null}
      </li>
    )
  }

  return (
    <div className="space-y-2">
      {settings.document_catalog.map((entry) => {
        const files = booking.attachments.filter((a) => a.category === entry.category)
        const uploading = busy === entry.category
        const protectLast = entry.required && files.length === 1
        const selectable = canManage && entry.multiple && files.length > 1
        const chosen = files.filter((f) => selected.has(f.id))
        const allChosen = files.length > 0 && chosen.length === files.length
        // A required type must keep one file; the backend refuses otherwise.
        const bulkBlocked = entry.required && chosen.length >= files.length
        return (
          <div
            key={entry.category}
            className={`rounded-lg border p-3 ${
              entry.required && files.length === 0 ? 'border-amber-200 bg-amber-50/40' : 'border-line bg-surface'
            }`}
          >
            <div className="flex flex-wrap items-center gap-2">
              <Document className="size-4 shrink-0 text-ink-muted" />
              <span className="text-sm font-medium text-ink">{entry.label}</span>
              {entry.required ? (
                <span className="badge bg-brand-50 text-brand-700">Required</span>
              ) : (
                <span className="badge bg-slate-100 text-slate-500">Optional</span>
              )}
              <span className="text-xs text-ink-muted">{entry.multiple ? 'Multiple files' : 'Single file'}</span>

              {canManage ? (
                <>
                  <input
                    ref={(node) => {
                      inputs.current[entry.category] = node
                    }}
                    type="file"
                    className="hidden"
                    multiple={entry.multiple}
                    accept={ALLOWED.join(',')}
                    data-testid={`upload-${entry.category}`}
                    onChange={(event) => {
                      const chosenFiles = Array.from(event.target.files ?? [])
                      event.target.value = ''
                      if (chosenFiles.length) void upload(entry.category, chosenFiles)
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => inputs.current[entry.category]?.click()}
                    className="btn-secondary btn-sm ml-auto"
                    disabled={uploading}
                  >
                    {uploading ? <Spinner className="size-3.5" /> : <Upload className="size-3.5" />}
                    {files.length && !entry.multiple ? 'Replace' : files.length ? 'Add files' : 'Upload'}
                  </button>
                </>
              ) : null}
            </div>
            {entry.description ? <p className="mt-1 text-xs text-ink-muted">{entry.description}</p> : null}

            {selectable ? (
              <div className="mt-2 flex flex-wrap items-center gap-3 text-xs">
                <label className="inline-flex items-center gap-1.5 text-ink-muted">
                  <input
                    type="checkbox"
                    checked={allChosen}
                    onChange={(event) => files.forEach((f) => toggle(f.id, event.target.checked))}
                  />
                  Select all
                </label>
                <button
                  type="button"
                  className="btn-ghost btn-sm text-rose-600 hover:bg-rose-50 disabled:opacity-40"
                  disabled={chosen.length === 0 || bulkBlocked}
                  title={bulkBlocked ? `${entry.label} is required; keep at least one file.` : undefined}
                  onClick={() => setPendingDelete({ ids: chosen.map((f) => f.id), names: chosen.map((f) => f.original_filename) })}
                >
                  <Trash className="size-3.5" />
                  Delete selected{chosen.length ? ` (${chosen.length})` : ''}
                </button>
              </div>
            ) : null}

            {files.length > 0 ? (
              <ul className="mt-2 space-y-1.5">
                {files.map((file) =>
                  fileRow(file, {
                    selectable,
                    deletable: !protectLast,
                    lockedReason: entry.multiple
                      ? `${entry.label} is required; keep at least one file.`
                      : `${entry.label} is required; use Replace to upload a new version.`,
                  }),
                )}
              </ul>
            ) : (
              <p className="mt-1.5 text-xs text-ink-muted">{canManage ? 'No file attached yet.' : 'Not attached.'}</p>
            )}
          </div>
        )
      })}

      {retired.length > 0 ? (
        <div className="rounded-lg border border-line bg-surface p-3">
          <p className="text-sm font-medium text-ink">Documents from retired types</p>
          <p className="text-xs text-ink-muted">These document types are no longer offered for upload; existing files stay available.</p>
          {[...new Set(retired.map((file) => file.category_label))].map((label) => (
            <div key={label} className="mt-2">
              <p className="px-1 text-[11px] font-semibold tracking-wide text-ink-muted uppercase">{label}</p>
              <ul className="mt-1 space-y-1.5">
                {retired
                  .filter((file) => file.category_label === label)
                  .map((file) => fileRow(file, { selectable: false, deletable: true }))}
              </ul>
            </div>
          ))}
        </div>
      ) : null}

      <p className="pt-1 text-xs text-ink-muted">
        Up to {settings.max_file_size_mb} MB per file. Accepted formats: {ALLOWED.join(', ')}.
      </p>

      <ConfirmationModal
        open={pendingDelete !== null}
        onClose={() => setPendingDelete(null)}
        onConfirm={() => void confirmDelete()}
        title={pendingDelete && pendingDelete.ids.length > 1 ? `Delete ${pendingDelete.ids.length} documents?` : 'Delete this document?'}
        description="Only the selected files are removed. Other files stay attached."
        facts={(pendingDelete?.names ?? []).map((name, index) => ({ label: `File ${index + 1}`, value: name }))}
        confirmLabel="Delete"
        cancelLabel="Keep"
        busy={deleting}
      />
    </div>
  )
}
