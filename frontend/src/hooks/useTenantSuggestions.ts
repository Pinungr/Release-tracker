import { useEffect, useState } from 'react'
import { api } from '../services/api'
import type { TenantOption } from '../types'

/** Tenants whose name or code contains what the user typed (2+ characters). */
export function useTenantSuggestions(term: string, enabled = true): TenantOption[] {
  const [options, setOptions] = useState<TenantOption[]>([])
  useEffect(() => {
    const text = term.trim()
    if (!enabled || text.length < 2) {
      setOptions([])
      return
    }
    let active = true
    const timer = window.setTimeout(() => {
      api.lookupTenants(text)
        .then((rows) => { if (active) setOptions(rows) })
        .catch(() => { if (active) setOptions([]) })
    }, 180)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [term, enabled])
  return options
}

/** The suggestion whose name is exactly what was typed, ignoring case. */
export function exactTenant(options: TenantOption[], term: string): TenantOption | undefined {
  const text = term.trim().toLowerCase()
  return options.find((tenant) => tenant.name.toLowerCase() === text)
}
