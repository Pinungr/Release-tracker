import { useEffect, useId, useRef, useState } from 'react'
import { api } from '../services/api'
import type { TenantOption } from '../types'
import { Cross, Search } from './Icons'

/**
 * Tenant autocomplete. Typing a partial name ("NCA") suggests the matching
 * tenant ("NCAP"); picking one yields the tenant's real id, so filtering uses
 * the tenant entity rather than free text.
 */
export function TenantPicker({
  value,
  onChange,
  label = 'Tenant',
  placeholder = 'All tenants',
  id,
}: {
  value: TenantOption | null
  onChange: (tenant: TenantOption | null) => void
  label?: string
  placeholder?: string
  id?: string
}) {
  const fallbackId = useId()
  const inputId = id ?? fallbackId
  const listId = `${inputId}-options`
  const [text, setText] = useState(value?.name ?? '')
  const [options, setOptions] = useState<TenantOption[]>([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const generation = useRef(0)

  // Keep the box in step when the parent resets or changes the selection.
  useEffect(() => { setText(value?.name ?? '') }, [value])

  useEffect(() => {
    if (!open) return
    const term = text.trim()
    const request = ++generation.current
    const timer = window.setTimeout(() => {
      api.lookupTenants(term)
        .then((rows) => { if (request === generation.current) { setOptions(rows); setActive(0) } })
        .catch(() => { if (request === generation.current) setOptions([]) })
    }, 180)
    return () => window.clearTimeout(timer)
  }, [text, open])

  function choose(tenant: TenantOption) {
    onChange(tenant)
    setText(tenant.name)
    setOpen(false)
  }

  function clear() {
    onChange(null)
    setText('')
    setOptions([])
  }

  return (
    <div className="relative text-xs font-semibold text-ink-muted">
      <label htmlFor={inputId}>{label}</label>
      <div className="relative mt-1">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-muted" />
        <input
          id={inputId}
          role="combobox"
          aria-expanded={open && options.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          autoComplete="off"
          className="field pr-9 pl-9"
          value={text}
          placeholder={placeholder}
          maxLength={120}
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 120)}
          onChange={(event) => {
            setText(event.target.value)
            setOpen(true)
            // Editing the text drops the previous selection until one is chosen.
            if (value) onChange(null)
          }}
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown') { event.preventDefault(); setActive((i) => Math.min(i + 1, options.length - 1)) }
            else if (event.key === 'ArrowUp') { event.preventDefault(); setActive((i) => Math.max(i - 1, 0)) }
            else if (event.key === 'Enter' && open && options[active]) { event.preventDefault(); choose(options[active]) }
            else if (event.key === 'Escape') setOpen(false)
          }}
        />
        {text ? (
          <button type="button" aria-label="Clear tenant" className="absolute top-1/2 right-2 grid size-6 -translate-y-1/2 place-items-center rounded text-ink-muted hover:bg-canvas" onMouseDown={(e) => e.preventDefault()} onClick={clear}>
            <Cross className="size-3.5" />
          </button>
        ) : null}
      </div>
      {open && options.length > 0 ? (
        <ul id={listId} role="listbox" className="absolute z-40 mt-1 max-h-64 w-full overflow-y-auto rounded-lg border border-line bg-surface py-1 shadow-lg">
          {options.map((tenant, index) => (
            <li
              key={tenant.id}
              role="option"
              aria-selected={index === active}
              className={`flex cursor-pointer items-center justify-between gap-2 px-3 py-2 text-sm font-normal ${index === active ? 'bg-brand-50 text-brand-800' : 'text-ink hover:bg-canvas'}`}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => choose(tenant)}
            >
              <span className="font-medium">{tenant.name}</span>
              {!tenant.is_active ? <span className="text-xs text-ink-muted">inactive</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
