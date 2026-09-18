import { useRef, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { BookingDetail, DocumentCategory, PublicSettings } from '../types'
import { formatBytes } from '../utils/format'
import { Document, Download, Spinner, Trash, Upload } from './Icons'
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
  isAdmin: boolean
  canManage?: boolean
  readOnly?: boolean
  onUpdated: (booking: BookingDetail) => void
}

export function DocumentUploader({
  booking,
  settings,
  isAdmin,
  canManage: ownerCanManage = false,
  readOnly = false,
  onUpdated,
}: DocumentUploaderProps) {
  const toast = useToast()
  const [busy, setBusy] = useState<DocumentCategory | null>(null)
  const [downloading, setDownloading] = useState<number | null>(null)
  const inputs = useRef<Partial<Record<DocumentCategory, HTMLInputElement | null>>>({})
  const canManage = !readOnly && (isAdmin || ownerCanManage)

  async function upload(category: DocumentCategory, file: File) {
    const extension = `.${file.name.split('.').pop()?.toLowerCase() ?? ''}`
    if (!ALLOWED.includes(extension)) {
      toast.error('Unsupported file type', `Allowed formats: ${ALLOWED.join(', ')}`)
      return
    }
    if (file.size > settings.max_file_size_mb * 1024 * 1024) {
      toast.error(
        'File is too large',
        `${file.name} is ${formatBytes(file.size)}; the limit is ${settings.max_file_size_mb} MB.`,
      )
      return
    }
    setBusy(category)
    try {
      const updated = await api.uploadAttachment(booking.id, category, file)
      onUpdated(updated)
      toast.success('Document uploaded', file.name)
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

  async function remove(attachmentId: number, name: string) {
    setBusy('SUPPORTING_DOCUMENTS')
    try {
      const updated = await api.deleteAttachment(booking.id, attachmentId)
      onUpdated(updated)
      toast.success('Document removed', name)
    } catch (error) {
      toast.error('Could not remove the document', error instanceof ApiError ? error.message : '')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-2">
      {settings.document_catalog.map((entry) => {
        const files = booking.attachments.filter((a) => a.category === entry.category)
        const uploading = busy === entry.category
        return (
          <div
            key={entry.category}
            className={`rounded-lg border p-3 ${
              entry.required && files.length === 0
                ? 'border-amber-200 bg-amber-50/40'
                : 'border-line bg-surface'
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
              {entry.multiple ? (
                <span className="text-xs text-ink-muted">Multiple files allowed</span>
              ) : null}

              {canManage ? (
                <>
                  <input
                    ref={(node) => {
                      inputs.current[entry.category] = node
                    }}
                    type="file"
                    className="hidden"
                    accept={ALLOWED.join(',')}
                    onChange={(event) => {
                      const file = event.target.files?.[0]
                      event.target.value = ''
                      if (file) void upload(entry.category, file)
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => inputs.current[entry.category]?.click()}
                    className="btn-secondary btn-sm ml-auto"
                    disabled={uploading}
                  >
                    {uploading ? <Spinner className="size-3.5" /> : <Upload className="size-3.5" />}
                    {files.length && !entry.multiple ? 'Replace' : 'Upload'}
                  </button>
                </>
              ) : null}
            </div>

            {files.length > 0 ? (
              <ul className="mt-2 space-y-1.5">
                {files.map((file) => (
                  <li
                    key={file.id}
                    className="flex items-center gap-2 rounded-md bg-canvas px-2.5 py-1.5 text-xs"
                  >
                    <span className="min-w-0 flex-1 truncate font-medium text-ink">
                      {file.original_filename}
                    </span>
                    <span className="shrink-0 tnum text-ink-muted">{formatBytes(file.size_bytes)}</span>
                    {isAdmin || ownerCanManage ? (
                      <button
                        type="button"
                        onClick={() => void downloadFile(file.id, file.original_filename)}
                        className="btn-ghost btn-sm shrink-0 px-1.5"
                        aria-label={`Download ${file.original_filename}`}
                        disabled={downloading === file.id}
                      >
                        {downloading === file.id ? (
                          <Spinner className="size-3.5" />
                        ) : (
                          <Download className="size-3.5" />
                        )}
                      </button>
                    ) : null}
                    {canManage ? (
                      <button
                        type="button"
                        onClick={() => void remove(file.id, file.original_filename)}
                        className="btn-ghost btn-sm shrink-0 px-1.5 text-rose-600 hover:bg-rose-50"
                        aria-label={`Remove ${file.original_filename}`}
                      >
                        <Trash className="size-3.5" />
                      </button>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1.5 text-xs text-ink-muted">
                {canManage ? 'No file attached yet.' : 'Not attached.'}
              </p>
            )}
          </div>
        )
      })}

      <p className="pt-1 text-xs text-ink-muted">
        Up to {settings.max_file_size_mb} MB per file. Accepted formats: {ALLOWED.join(', ')}.
      </p>
    </div>
  )
}
