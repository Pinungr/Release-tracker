import { useEffect, useId, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { BookingDetail, GroupMember } from '../types'
import { Search, Spinner, User } from './Icons'
import { useToast } from './ToastNotification'

export function ReleaseManagerAssignee({ booking, onChanged }: { booking: BookingDetail; onChanged: () => void }) {
  const toast = useToast()
  const listId = useId()
  const savedName = booking.assigned_users[0]?.full_name ?? ''
  const savedId = booking.assigned_users[0]?.user_id
  const [name, setName] = useState(savedName)
  const [query, setQuery] = useState(savedName)
  const [editing, setEditing] = useState(false)
  const [suggestions, setSuggestions] = useState<GroupMember[]>([])
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState(false)
  const [busy, setBusy] = useState(false)
  const [highlighted, setHighlighted] = useState(-1)

  useEffect(() => {
    setName(savedName)
    setQuery(savedName)
    setEditing(false)
  }, [booking.id, savedId, savedName])

  useEffect(() => {
    setSuggestions([])
    setHighlighted(-1)
    setSearchError(false)
    if (!editing || query.trim().length < 2 || busy) {
      setSearching(false)
      return
    }
    setSearching(true)
    let active = true
    const timer = window.setTimeout(() => {
      void api.searchReleaseManagers(query.trim())
        .then((users) => { if (active) setSuggestions(users) })
        .catch(() => { if (active) setSearchError(true) })
        .finally(() => { if (active) setSearching(false) })
    }, 180)
    return () => { active = false; window.clearTimeout(timer) }
  }, [query, editing, busy])

  function resetSearch() {
    setEditing(false)
    setQuery(name)
    setSuggestions([])
  }

  async function assign(user?: GroupMember) {
    if (busy) return
    setBusy(true)
    setEditing(false)
    setSuggestions([])
    try {
      const updated = user
        ? await api.assignBookingUsers(booking.id, [user.id])
        : await api.assignBookingToMe(booking.id)
      const fullName = updated.assigned_users[0]?.full_name ?? ''
      setName(fullName)
      setQuery(fullName)
      toast.success('Release Manager assigned.', fullName)
      onChanged()
    } catch (error) {
      setQuery(name)
      toast.error('Could not update the assignee', error instanceof ApiError ? error.message : 'Please try again.')
    } finally {
      setBusy(false)
    }
  }

  const showSuggestions = editing && query.trim().length >= 2 && !busy
  return (
    <section className="rounded-xl border border-line bg-canvas/50 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">Release Manager assignee</h3>
          <p className="mt-1 text-xs text-ink-muted">Search after 2 letters. Selecting a name saves it and replaces the current assignee.</p>
        </div>
        {booking.can_assign_self && (
          <button type="button" className="btn-secondary" disabled={busy} onClick={() => void assign()}>
            <User className="size-4" />Assign to me
          </button>
        )}
      </div>
      <div className="relative mt-3" onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) resetSearch()
      }}>
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-muted" />
        <input
          role="combobox"
          aria-label="Release Manager assignee"
          aria-autocomplete="list"
          aria-expanded={showSuggestions}
          aria-controls={showSuggestions ? listId : undefined}
          aria-activedescendant={showSuggestions && highlighted >= 0 ? `${listId}-${highlighted}` : undefined}
          className="field pl-9 pr-9"
          value={query}
          disabled={busy}
          onFocus={(event) => event.currentTarget.select()}
          onChange={(event) => { setQuery(event.target.value); setEditing(true) }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') { event.preventDefault(); resetSearch() }
            if (showSuggestions && suggestions.length && ['ArrowDown', 'ArrowUp'].includes(event.key)) {
              event.preventDefault()
              setHighlighted((current) => (current + (event.key === 'ArrowDown' ? 1 : suggestions.length - 1) + suggestions.length) % suggestions.length)
            }
            if (event.key === 'Enter' && showSuggestions && highlighted >= 0 && suggestions[highlighted]) {
              event.preventDefault()
              void assign(suggestions[highlighted])
            }
          }}
          placeholder="Search Release Manager"
          autoComplete="off"
        />
        {(busy || searching) && <Spinner className="absolute right-3 top-1/2 size-4 -translate-y-1/2" />}
        {showSuggestions && (
          <div id={listId} role="listbox" aria-label="Release Manager suggestions" className="absolute z-20 mt-1 max-h-60 w-full overflow-auto rounded-lg border border-line bg-white shadow-lg">
            {searching ? <p role="status" className="px-3 py-3 text-xs text-ink-muted">Searching…</p> : suggestions.length ? suggestions.map((user, index) => (
              <button
                key={user.id}
                id={`${listId}-${index}`}
                type="button"
                role="option"
                aria-selected={highlighted === index}
                className={`flex w-full items-center justify-between gap-3 border-b border-line/60 px-3 py-2 text-left last:border-0 hover:bg-canvas ${highlighted === index ? 'bg-brand-50' : ''}`}
                onClick={() => void assign(user)}
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-ink">{user.full_name}</span>
                  <span className="block truncate text-xs text-ink-muted">@{user.username} · {user.email}</span>
                </span>
                <span className="text-xs font-semibold text-brand-700">Assign</span>
              </button>
            )) : <p role="status" className="px-3 py-3 text-xs text-ink-muted">{searchError ? 'Search unavailable. Please try again.' : 'No matching Release Manager found.'}</p>}
          </div>
        )}
      </div>
      {booking.assigned_users.length > 1 && <p className="mt-2 text-xs text-ink-muted">This schedule has multiple existing assignees. Select one person to replace them.</p>}
    </section>
  )
}
