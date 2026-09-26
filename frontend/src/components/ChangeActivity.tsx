import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { BookingComment, CommentImage } from '../types'
import { formatTimestamp } from '../utils/dates'
import { Paperclip, Send, Spinner, Smile, ImageIcon } from './Icons'
import { CommentImagePreview, ExistingImagePicker, imageKey } from './CommentImages'

export function ChangeActivity({ bookingId, isAdmin, timezone }: {
  bookingId: number; isAdmin: boolean; timezone: string
}) {
  const textarea = useRef<HTMLTextAreaElement>(null)
  const [picker, setPicker] = useState<'emoji' | 'image' | null>(null)
  const [selectedImages, setSelectedImages] = useState<CommentImage[]>([])
  const [comments, setComments] = useState<BookingComment[]>([])
  const [body, setBody] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const fileInput = useRef<HTMLInputElement>(null)
  const [fileError, setFileError] = useState('')
  const [internal, setInternal] = useState(false)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [more, setMore] = useState(false)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    api.getBookingComments(bookingId).then(rows => {
      if (active) { setComments(rows); setMore(rows.length === 50) }
    }).catch(e => { if (active) setError(e instanceof ApiError ? e.message : 'Could not load comments.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [bookingId, reload])
  async function post() {
    if (!body.trim() || busy || fileError) return
    setBusy(true); setError('')
    try {
      const refs = selectedImages.map(({kind, attachment_id, comment_id}) => ({kind, attachment_id, comment_id}))
      if (files.length) {
        if (refs.length) await api.uploadComment(bookingId, body.trim(), isAdmin && internal, files, refs)
        else await api.uploadComment(bookingId, body.trim(), isAdmin && internal, files)
      } else if (refs.length) await api.addBookingComment(bookingId, body.trim(), isAdmin && internal, refs)
      else await api.addBookingComment(bookingId, body.trim(), isAdmin && internal)
      setSelectedImages([]); setPicker(null)
      setFiles([]); if (fileInput.current) fileInput.current.value = ''; setFileError('')
      setBody(''); setReload(n => n + 1)
    } catch (e) { setError(e instanceof ApiError ? e.message : 'Could not post comment. Your draft has been kept.') }
    finally { setBusy(false) }
  }
  function insertEmoji(emoji: string) {
    const start = textarea.current?.selectionStart ?? body.length
    const end = textarea.current?.selectionEnd ?? start
    const next = body.slice(0, start) + emoji + body.slice(end)
    if (next.length > 5000) { setError('The comment is limited to 5,000 characters.'); return }
    setBody(next); setPicker(null)
    requestAnimationFrame(() => { textarea.current?.focus(); textarea.current?.setSelectionRange(start + emoji.length, start + emoji.length) })
  }
  function selectImage(image: CommentImage) {
    if (selectedImages.some(existing => imageKey(existing) === imageKey(image))) { setPicker(null); return }
    if (selectedImages.length >= 10) { setError('Insert up to 10 existing images per comment.'); return }
    setSelectedImages(current => [...current, image]); setPicker(null)
    textarea.current?.focus()
  }
  function selectFiles(selected: File[]) {
    const allowed = /\.(pdf|docx?|xlsx?|csv|txt|zip|sql|png|jpe?g)$/i
    const message = selected.length > 10 ? 'Attach at most 10 files per comment.' : selected.some(f => f.size > 20 * 1024 * 1024) ? 'Each file must be 20 MB or smaller.' : selected.some(f => f.size === 0) ? 'Empty files cannot be attached.' : selected.some(f => !allowed.test(f.name)) ? 'Unsupported attachment type.' : ''
    setFiles(selected); setFileError(message)
  }
  async function download(commentId: number, attachment: {id: string; original_filename: string}) {
    try { await api.downloadCommentAttachment(bookingId, commentId, attachment.id, attachment.original_filename) }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Could not download attachment.') }
  }
  async function loadOlder() {
    setBusy(true); setError('')
    try {
      const rows = await api.getBookingComments(bookingId, comments[comments.length - 1]?.id)
      setComments(current => [...current, ...rows]); setMore(rows.length === 50)
    } catch { setError('Could not load older comments. Please retry.') }
    finally { setBusy(false) }
  }
  return <section className="card p-5" aria-label="Change comments">
    <h2 className="text-lg font-bold text-ink">Comments</h2>
    <p className="mt-1 mb-4 text-sm text-ink-muted">Conversation stays here. Operational history is available from the Audit tab above.</p>
    <div className="space-y-4">
      <div className="overflow-hidden rounded-xl border border-line bg-surface transition-shadow focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-500/15">
        <label htmlFor="change-comment" className="sr-only">{internal && isAdmin ? 'Internal RM note' : 'Comment visible to the requester and RM team'}</label>
        <textarea ref={textarea} id="change-comment" className="block min-h-28 w-full resize-y border-0 bg-transparent px-4 pt-3 pb-2 text-sm text-ink outline-none placeholder:text-ink-muted focus:ring-0 disabled:opacity-60" value={body} onChange={e => setBody(e.target.value)} maxLength={5000} disabled={busy} placeholder={internal && isAdmin ? 'Write an internal RM note…' : 'Ask a question or share an update…'} />
        <input id="comment-files" ref={fileInput} type="file" multiple disabled={busy} aria-label="Attach files · 20 MB maximum per file" accept=".pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.zip,.sql,.png,.jpg,.jpeg" onChange={e => {
          const added = Array.from(e.target.files ?? [])
          if (added.length) selectFiles([...files, ...added])
          e.target.value = ''
        }} className="hidden" />
        {files.length > 0 && <div className="flex flex-wrap gap-2 px-4 py-2" aria-label="Selected attachments">
          {files.map((file, index) => <span key={`${index}-${file.name}`} className="inline-flex max-w-full items-center gap-2 rounded-md border border-line bg-canvas px-2 py-1 text-xs text-ink">
            <Paperclip className="size-3.5 shrink-0" />
            <span className="min-w-0 truncate" title={file.name}>{file.name}</span>
            <button type="button" aria-label={`Remove ${file.name}`} title="Remove attachment" disabled={busy} className="grid size-6 shrink-0 place-items-center rounded hover:bg-slate-200 focus-visible:outline-2 focus-visible:outline-brand-500" onClick={() => selectFiles(files.filter((_, i) => i !== index))}>×</button>
          </span>)}
        </div>}
        {selectedImages.length > 0 && <div className="grid gap-2 px-4 py-2 sm:grid-cols-2" aria-label="Images inserted in draft">
          {selectedImages.map(image => <div key={imageKey(image)} className="min-w-0"><CommentImagePreview bookingId={bookingId} image={image} /><button type="button" className="btn-ghost btn-sm mt-1" disabled={busy} onClick={() => setSelectedImages(current => current.filter(item => imageKey(item) !== imageKey(image)))} aria-label={`Remove image ${image.original_filename}`}>Remove image</button></div>)}
        </div>}
        {picker === 'emoji' && <div role="dialog" aria-label="Choose an emoji" className="mx-3 mb-3 rounded-lg border border-line bg-canvas p-3" onKeyDown={e => {if(e.key === 'Escape') setPicker(null)}}>
          <div className="mb-2 flex items-center justify-between"><strong className="text-sm">Emoji</strong><button type="button" aria-label="Close emoji picker" className="btn-ghost btn-sm" onClick={() => setPicker(null)}>×</button></div>
          <div className="flex flex-wrap gap-1">{[
            ['😀', 'Smile'], ['😊', 'Happy'], ['👍', 'Thumbs up'], ['👎', 'Thumbs down'], ['✅', 'Done'], ['❌', 'No'], ['🎉', 'Celebrate'], ['🚀', 'Launch'],
            ['🙏', 'Thanks'], ['👏', 'Applause'], ['👀', 'Review'], ['🤔', 'Thinking'], ['⚠️', 'Warning'], ['🔧', 'Fix'], ['🕒', 'Waiting'], ['❤️', 'Heart'],
          ].map(([emoji, label]) => <button type="button" key={label} aria-label={label} title={label} className="grid size-10 place-items-center rounded text-xl hover:bg-surface focus-visible:outline-2 focus-visible:outline-brand-500" onClick={() => insertEmoji(emoji)}>{emoji}</button>)}</div>
        </div>}
        {picker === 'image' && <ExistingImagePicker key={String(internal)} bookingId={bookingId} internal={isAdmin && internal} onSelect={selectImage} onClose={() => setPicker(null)} />}
        {fileError && <p role="alert" className="px-4 py-2 text-sm text-rose-700">{fileError}</p>}
        <div className="flex min-h-12 flex-wrap items-center justify-end gap-2 px-3 pb-2">
          {isAdmin && <label className="mr-auto flex items-center gap-2 text-xs text-ink-muted" title="Only the Owner and Release Managers can see this note and its attachments"><input type="checkbox" checked={internal} disabled={busy} onChange={e => {
            const value = e.target.checked
            if (!value && selectedImages.some(image => image.internal)) {
              setSelectedImages(current => current.filter(image => !image.internal))
              setError('Internal RM images were removed when switching to a public comment.')
            }
            setInternal(value)
          }} />Internal RM note</label>}
          <div role="group" aria-label="Comment actions" className="flex items-center gap-1">
            <button type="button" aria-label="Add emoji" title="Add emoji" aria-expanded={picker === 'emoji'} disabled={busy} className="grid size-9 place-items-center rounded-md text-ink-muted hover:bg-canvas focus-visible:outline-2 focus-visible:outline-brand-500 disabled:opacity-40" onClick={() => setPicker(current => current === 'emoji' ? null : 'emoji')}><Smile className="size-5" /></button>
            <button type="button" aria-label="Insert uploaded image" title="Insert an already uploaded image" aria-expanded={picker === 'image'} disabled={busy} className="grid size-9 place-items-center rounded-md text-ink-muted hover:bg-canvas focus-visible:outline-2 focus-visible:outline-brand-500 disabled:opacity-40" onClick={() => setPicker(current => current === 'image' ? null : 'image')}><ImageIcon className="size-5" /></button>
            <button type="button" aria-label="Attach files" title="Attach files (20 MB per file)" disabled={busy} className="grid size-9 place-items-center rounded-md text-ink-muted transition-colors hover:bg-canvas hover:text-ink focus-visible:outline-2 focus-visible:outline-brand-500 disabled:opacity-40" onClick={() => fileInput.current?.click()}><Paperclip className="size-5" /></button>
            <span aria-hidden="true" className="mx-1 h-5 w-px bg-line" />
            <button type="button" aria-label={internal && isAdmin ? 'Add internal note' : 'Add comment'} title={internal && isAdmin ? 'Send internal note' : 'Send comment'} className="grid size-9 place-items-center rounded-md text-brand-600 transition-colors hover:bg-brand-50 focus-visible:outline-2 focus-visible:outline-brand-500 disabled:cursor-not-allowed disabled:text-ink-muted disabled:opacity-40" disabled={busy || !body.trim() || Boolean(fileError)} onClick={() => void post()}>{busy ? <Spinner className="size-5" /> : <Send className="size-5" />}</button>
          </div>
        </div>
      </div>
      {error && <div role="alert" className="text-sm text-rose-700">{error} <button className="underline" onClick={() => setReload(n => n + 1)}>Reload comments</button></div>}
      {loading ? <p role="status">Loading comments…</p> : comments.length === 0 ? <p className="text-sm text-ink-muted">No comments yet. Start the conversation.</p> : null}
      {comments.map(c => <article key={c.id} className={`rounded-lg border p-4 ${c.internal ? 'border-amber-200 bg-amber-50' : 'border-line bg-surface'}`}>
        <div className="flex flex-wrap items-center gap-2 text-sm"><strong>{c.author_name}</strong>{c.internal && <span className="badge bg-amber-100 text-amber-900">Internal RM note</span>}<time className="ml-auto text-xs text-ink-muted">{formatTimestamp(c.created_at, timezone)}</time></div>
        <p className="mt-2 whitespace-pre-wrap break-words text-sm text-ink">{c.body}</p>
        {c.images?.length ? <div className="mt-3 grid gap-3 sm:grid-cols-2" aria-label="Referenced images">{c.images.map(image => <CommentImagePreview key={imageKey(image)} bookingId={bookingId} image={image} />)}</div> : null}
        {c.attachments?.length ? <ul className="mt-3 space-y-2" aria-label="Comment attachments">{c.attachments.map(a => <li key={a.id}><button className="btn-secondary max-w-full whitespace-normal break-all text-left" onClick={() => void download(c.id, a)}>{a.original_filename} · {(a.size_bytes / 1024 / 1024).toFixed(2)} MB · Download</button></li>)}</ul> : null}
      </article>)}
      {more && <button className="btn-secondary" disabled={busy} onClick={() => void loadOlder()}>Load older comments</button>}
    </div>
  </section>
}
