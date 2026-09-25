import { useEffect, useRef, useState } from 'react'
import type { CommentImage } from '../types'
import { api, ApiError } from '../services/api'
import { ImageIcon } from './Icons'

export const imageKey = (image: CommentImage) => `${image.kind}:${image.comment_id ?? ''}:${image.attachment_id}`

/** Fetch only when near the viewport; revoke protected blob URLs on unmount. */
export function CommentImagePreview({ bookingId, image }: {bookingId: number; image: CommentImage}) {
  const host = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)
  const [url, setUrl] = useState('')
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') { setVisible(true); return }
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) { setVisible(true); observer.disconnect() }
    }, {rootMargin: '100px'})
    if (host.current) observer.observe(host.current)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    if (!visible) return
    const controller = new AbortController()
    let objectUrl = ''
    setUrl(''); setFailed(false)
    api.getCommentImage(bookingId, image, controller.signal).then(blob => {
      if (!controller.signal.aborted) { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl) }
    }).catch(() => { if (!controller.signal.aborted) setFailed(true) })
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [bookingId, image.kind, image.comment_id, image.attachment_id, visible])
  return <div ref={host} className="min-h-16 overflow-hidden rounded-lg border border-line bg-surface p-2">
    {failed ? <p className="text-xs text-ink-muted">Image unavailable: {image.original_filename}</p> : url ? <img src={url} alt={image.original_filename} className="max-h-72 max-w-full rounded object-contain" onError={() => setFailed(true)} /> : <p className="p-3 text-xs text-ink-muted">Loading image…</p>}
    <p className="mt-1 break-all text-xs text-ink-muted">{image.original_filename}{image.internal ? ' · Internal RM image' : ''}</p>
  </div>
}

export function ExistingImagePicker({bookingId, internal, onSelect, onClose}: {
  bookingId: number; internal: boolean; onSelect: (image: CommentImage) => void; onClose: () => void
}) {
  const [images, setImages] = useState<CommentImage[]>([])
  const [before, setBefore] = useState<number | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let active = true
    setBusy(true); setImages([]); setError(''); setBefore(null)
    api.listCommentImages(bookingId, internal).then(result => {
      if (active) { setImages(result.images); setBefore(result.next_before_id) }
    }).catch(e => { if (active) setError(e instanceof ApiError ? e.message : 'Could not load images.') })
      .finally(() => { if (active) setBusy(false) })
    return () => {active = false}
  }, [bookingId, internal, retry])
  async function more() {
    if (!before) return
    setBusy(true); setError('')
    try {
      const result = await api.listCommentImages(bookingId, internal, before)
      setImages(current => [...current, ...result.images]); setBefore(result.next_before_id)
    } catch { setError('Could not load older images.') }
    finally {setBusy(false)}
  }
  return <div role="dialog" aria-label="Previously uploaded images" className="mx-3 mb-3 rounded-lg border border-line bg-canvas p-3" onKeyDown={e => {if(e.key === 'Escape') onClose()}}>
    <div className="mb-2 flex items-center justify-between gap-2"><strong className="text-sm">Uploaded images</strong><button type="button" className="btn-ghost btn-sm" onClick={onClose} aria-label="Close image picker">×</button></div>
    {error && <p role="alert" className="text-sm text-rose-700">{error} <button className="underline" onClick={() => setRetry(n=>n+1)}>Retry</button></p>}
    <div className="grid max-h-60 gap-2 overflow-y-auto sm:grid-cols-2">
      {images.map(image => <button type="button" key={imageKey(image)} className="flex items-center gap-2 rounded border border-line bg-surface p-3 text-left text-sm hover:border-brand-500" onClick={() => onSelect(image)}>
        <ImageIcon className="size-5 shrink-0 text-ink-muted" /><span className="min-w-0 break-all">{image.original_filename}<span className="block text-xs text-ink-muted">{image.internal ? 'Internal RM note' : image.kind === 'document' ? 'Deployment document' : 'Comment attachment'}</span></span>
      </button>)}
    </div>
    {busy ? <p role="status" className="mt-2 text-xs">Loading images…</p> : !images.length ? <p className="text-sm text-ink-muted">No PNG or JPEG images uploaded to this schedule yet.</p> : null}
    {before && <button type="button" disabled={busy} className="btn-secondary btn-sm mt-2" onClick={() => void more()}>Load older images</button>}
  </div>
}
