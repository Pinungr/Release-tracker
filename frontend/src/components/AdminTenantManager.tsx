import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { AdminTenant } from '../types'
import { Plus, Spinner } from './Icons'
import { TextField } from './FormControls'
import { useToast } from './ToastNotification'

const EMPTY = { name: '', tenant_code: '', description: '' }

/**
 * The tenant master. Tenants exist only here — scheduling picks one from this
 * list and can never create one as a side effect.
 */
export function AdminTenantManager({ onChanged }: { onChanged: () => void }) {
  const toast = useToast()
  const [tenants, setTenants] = useState<AdminTenant[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState(EMPTY)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    setError(null)
    api
      .listAdminTenants()
      .then(setTenants)
      .catch((caught) => {
        setTenants([])
        setError(caught instanceof ApiError ? caught.message : 'Could not load tenants.')
      })
  }, [])

  useEffect(load, [load])

  function reset() {
    setDraft(EMPTY)
    setEditingId(null)
  }

  async function submit() {
    if (!draft.name.trim() || !draft.tenant_code.trim()) {
      toast.error('A tenant needs a name and a code.')
      return
    }
    setBusy(true)
    try {
      const payload = {
        name: draft.name.trim(),
        tenant_code: draft.tenant_code.trim().toUpperCase(),
        description: draft.description.trim() || null,
      }
      if (editingId) await api.updateAdminTenant(editingId, payload)
      else await api.createAdminTenant(payload)
      reset()
      load()
      onChanged()
      toast.success(editingId ? 'Tenant updated.' : 'Tenant added.')
    } catch (caught) {
      toast.error('Could not save the tenant', caught instanceof ApiError ? caught.message : '')
    } finally {
      setBusy(false)
    }
  }

  async function toggle(tenant: AdminTenant) {
    setBusy(true)
    try {
      await api.setTenantActive(tenant.id, !tenant.is_active)
      load()
      onChanged()
      toast.success(tenant.is_active ? 'Tenant deactivated.' : 'Tenant activated.', tenant.name)
    } catch (caught) {
      toast.error('Could not update the tenant', caught instanceof ApiError ? caught.message : '')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <h3 className="text-sm font-semibold text-ink">Tenant master</h3>
      <p className="mt-0.5 text-xs text-ink-muted">
        A tenant is selected per change record. Deactivating one removes it from the scheduling
        form without touching its history.
      </p>

      <form
        className="mt-4 mb-5 grid gap-4 rounded-lg border border-line bg-canvas/50 p-4 sm:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
      >
        <TextField
          label="Tenant name"
          name="tenant_name"
          required
          value={draft.name}
          onChange={(v) => setDraft({ ...draft, name: v })}
          placeholder="EPCAT"
          maxLength={120}
        />
        <TextField
          label="Tenant code"
          name="tenant_code"
          required
          value={draft.tenant_code}
          onChange={(v) => setDraft({ ...draft, tenant_code: v })}
          placeholder="EPCAT"
          hint="Short unique identifier; stored upper-case."
          maxLength={64}
        />
        <TextField
          label="Description"
          name="tenant_description"
          value={draft.description}
          onChange={(v) => setDraft({ ...draft, description: v })}
          hint="Optional."
          className="sm:col-span-2"
        />
        <div className="flex gap-2 sm:col-span-2">
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? <Spinner className="size-4" /> : <Plus className="size-4" />}
            {editingId ? 'Update tenant' : 'Add tenant'}
          </button>
          {editingId ? (
            <button type="button" className="btn-secondary" onClick={reset}>
              Cancel edit
            </button>
          ) : null}
        </div>
      </form>

      {error ? <p className="mb-3 text-sm text-rose-600">{error}</p> : null}

      {!tenants ? (
        <div className="flex items-center gap-2 py-8 text-sm text-ink-muted">
          <Spinner className="size-4" />
          Loading tenants…
        </div>
      ) : tenants.length === 0 ? (
        <p className="text-sm text-ink-muted">
          No tenants yet. Add one before anybody can schedule a change.
        </p>
      ) : (
        <ul className="space-y-2">
          {tenants.map((tenant) => (
            <li
              key={tenant.id}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-line p-3"
            >
              <span className="text-sm font-semibold text-ink">{tenant.name}</span>
              {tenant.tenant_code ? (
                <span className="badge bg-canvas text-ink-muted ring-1 ring-line">
                  {tenant.tenant_code}
                </span>
              ) : null}
              <span
                className={`badge ${
                  tenant.is_active
                    ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100'
                    : 'bg-slate-100 text-slate-500 ring-1 ring-slate-200'
                }`}
              >
                {tenant.is_active ? 'Active' : 'Inactive'}
              </span>
              {tenant.description ? (
                <span className="text-xs text-ink-muted">{tenant.description}</span>
              ) : null}

              <span className="ml-auto flex gap-1.5">
                <button
                  type="button"
                  className="btn-secondary btn-sm"
                  onClick={() => {
                    setEditingId(tenant.id)
                    setDraft({
                      name: tenant.name,
                      tenant_code: tenant.tenant_code ?? '',
                      description: tenant.description ?? '',
                    })
                  }}
                >
                  Edit
                </button>
                <button
                  type="button"
                  className="btn-ghost btn-sm"
                  disabled={busy}
                  onClick={() => void toggle(tenant)}
                >
                  {tenant.is_active ? 'Deactivate' : 'Activate'}
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
