import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { AccessGroup, GroupMember, ManagedUser } from '../types'
import { groupUrl, resolveGroupRoute } from '../utils/groupRoutes'
import { Alert, ChevronLeft, ChevronRight, Plus, Search, Shield, Spinner, Trash, User } from './Icons'
import { ConfirmationModal, Modal } from './Modal'
import { useToast } from './ToastNotification'

const LABELS: Record<AccessGroup['group_type'], string> = {
  MEMBER_POOL: 'Member pool',
  RELEASE_MANAGERS: 'Release team',
  TENANTS: 'Tenant directory',
  TENANT_SUBGROUP: 'Tenant group',
  MANAGEMENT: 'Management',
  CUSTOM: 'Custom group',
}
const DESCRIPTIONS: Record<AccessGroup['group_type'], string> = {
  MEMBER_POOL: 'Unassigned accounts, ready to join a tenant or working group.',
  RELEASE_MANAGERS: 'The team responsible for coordinating and delivering releases.',
  TENANTS: 'Organize tenant access through dedicated tenant groups.',
  TENANT_SUBGROUP: 'Manage the people who belong to this tenant.',
  MANAGEMENT: 'Keep your management team organized in one place.',
  CUSTOM: 'Bring together the people who work on a shared responsibility.',
}
const TONES: Record<AccessGroup['group_type'], string> = {
  MEMBER_POOL: 'bg-slate-100 text-slate-600',
  RELEASE_MANAGERS: 'bg-indigo-50 text-indigo-600',
  TENANTS: 'bg-teal-50 text-teal-700',
  TENANT_SUBGROUP: 'bg-teal-50 text-teal-700',
  MANAGEMENT: 'bg-violet-50 text-violet-600',
  CUSTOM: 'bg-amber-50 text-amber-700',
}
const ORDER = ['MEMBER_POOL', 'RELEASE_MANAGERS', 'TENANTS', 'MANAGEMENT', 'CUSTOM']
const errorMessage = (e: unknown) => (e instanceof ApiError ? e.message : 'Please try again.')
const initials = (name: string) =>
  name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
    .toUpperCase() || '?'

function GroupIcon({ group, small = false }: { group: AccessGroup; small?: boolean }) {
  return (
    <span
      className={`grid shrink-0 place-items-center rounded-xl ${small ? 'size-8' : 'size-12'} ${TONES[group.group_type]}`}
    >
      <Shield className={small ? 'size-4' : 'size-6'} />
    </span>
  )
}

function GroupCard({ group, childCount }: { group: AccessGroup; childCount: number }) {
  return (
    <a
      href={groupUrl(group)}
      className="group flex h-full flex-col rounded-2xl border border-line bg-white p-5 shadow-card transition hover:border-brand-500/40 hover:shadow-raised"
    >
      <div className="flex items-center justify-between gap-3">
        <GroupIcon group={group} />
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-medium ${group.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}
        >
          {group.is_active ? 'Active' : 'Inactive'}
        </span>
      </div>
      <p className="mt-5 text-xs font-semibold tracking-wide text-ink-muted uppercase">
        {LABELS[group.group_type]}
      </p>
      <h3 className="mt-1 break-words text-lg font-semibold text-ink group-hover:text-brand-600">
        {group.name}
      </h3>
      <p className="mt-2 flex-1 text-sm leading-6 text-ink-muted">
        {group.description || DESCRIPTIONS[group.group_type]}
      </p>
      <div className="mt-5 flex items-center justify-between border-t border-line pt-4 text-sm">
        <span className="text-ink-muted">
          {group.group_type === 'TENANTS'
            ? `${childCount} tenant groups`
            : `${group.member_count} member${group.member_count === 1 ? '' : 's'}`}
        </span>
        <span className="flex items-center gap-1 font-semibold text-brand-600">
          Open group
          <ChevronRight className="size-4" />
        </span>
      </div>
    </a>
  )
}

/** Dedicated URL-backed workspace; each group is a separate page. */
export function AdminGroupManager({ isOwner, route }: { isOwner: boolean; route: string }) {
  const toast = useToast()
  const [groups, setGroups] = useState<AccessGroup[] | null>(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [busy, setBusy] = useState(false)
  const requestVersion = useRef(0)
  const loadGroups = useCallback(async () => {
    const version = ++requestVersion.current
    try {
      const rows = await api.listGroups()
      if (version === requestVersion.current) {
        setGroups(rows)
        setError('')
      }
    } catch (e) {
      if (version === requestVersion.current) setError(errorMessage(e))
    }
  }, [])
  useEffect(() => {
    void loadGroups()
    return () => {
      requestVersion.current++
    }
  }, [loadGroups])
  useEffect(() => {
    setQuery('')
    window.scrollTo(0, 0)
  }, [route])
  const selected = resolveGroupRoute(route, groups ?? [])
  const selectedId = selected?.id ?? null
  const parent = groups?.find((g) => g.id === selected?.parent_group_id)
  const overview = /^#\/admin\/groups\/?$/.test(route)
  const roots = useMemo(
    () =>
      (groups ?? [])
        .filter((g) => g.parent_group_id == null)
        .sort(
          (a, b) => ORDER.indexOf(a.group_type) - ORDER.indexOf(b.group_type) || a.name.localeCompare(b.name),
        ),
    [groups],
  )
  const children = (id: number) => (groups ?? []).filter((g) => g.parent_group_id === id)
  const filtered = (groups ?? []).filter((g) =>
    query.trim()
      ? `${g.name} ${LABELS[g.group_type]}`.toLowerCase().includes(query.trim().toLowerCase())
      : g.parent_group_id == null,
  )

  async function createGroup() {
    if (!newName.trim() || busy) return
    setBusy(true)
    try {
      const group = await api.createGroup({ name: newName.trim() })
      setGroups((current) => [...(current ?? []), group])
      setCreateOpen(false)
      setNewName('')
      window.location.hash = groupUrl(group)
      toast.success('Group created', `${group.name} is ready for members.`)
      await loadGroups()
    } catch (e) {
      toast.error('Could not create group', errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  function navLink(group: AccessGroup, nested = false) {
    const active = group.id === selectedId
    return (
      <a
        key={group.id}
        href={groupUrl(group)}
        aria-current={active ? 'page' : undefined}
        className={`flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm transition ${nested ? 'ml-6 border-l border-line' : ''} ${active ? 'bg-brand-50 font-semibold text-brand-700' : 'text-ink-muted hover:bg-slate-50 hover:text-ink'}`}
      >
        {!nested && <GroupIcon group={group} small />}
        <span className="min-w-0 flex-1 break-words">{group.name}</span>
        <span className="rounded-md bg-white/80 px-1.5 py-0.5 text-xs tabular-nums">
          {group.group_type === 'TENANTS' ? children(group.id).length : group.member_count}
        </span>
      </a>
    )
  }

  return (
    <main className="mx-auto w-full max-w-[88rem] flex-1 px-4 py-6 sm:px-6 lg:px-8">
      <nav aria-label="Breadcrumb" className="mb-6 flex flex-wrap items-center gap-2 text-sm text-ink-muted">
        <a href="#" className="hover:text-brand-600">
          Schedule
        </a>
        <ChevronRight className="size-3.5" />
        <a href="#/admin/groups" className="hover:text-brand-600">
          Groups
        </a>
        {selected && (
          <>
            <ChevronRight className="size-3.5" />
            {selected.parent_group_id && (
              <>
                <a className="hover:text-brand-600" href={parent ? groupUrl(parent) : '#/admin/groups'}>
                  Tenants
                </a>
                <ChevronRight className="size-3.5" />
              </>
            )}
            <span className="font-medium text-ink" aria-current="page">
              {selected.name}
            </span>
          </>
        )}
      </nav>
      <div className="mb-5 lg:hidden">
        <label htmlFor="mobile-group-nav" className="field-label">
          Navigate groups
        </label>
        <select
          id="mobile-group-nav"
          className="field"
          value={selectedId ?? 'all'}
          onChange={(e) => {
            const group = groups?.find((g) => g.id === Number(e.target.value))
            window.location.hash = group ? groupUrl(group) : '#/admin/groups'
          }}
        >
          <option value="all">All groups</option>
          {roots.flatMap((group) => [
            <option key={group.id} value={group.id}>
              {group.name}
            </option>,
            ...children(group.id).map((child) => (
              <option key={child.id} value={child.id}>
                Tenants / {child.name}
              </option>
            )),
          ])}
        </select>
      </div>
      <div className="grid items-start gap-6 lg:grid-cols-[248px_minmax(0,1fr)]">
        <aside className="hidden lg:block rounded-2xl border border-line bg-white p-3 shadow-card lg:sticky lg:top-24">
          <div className="px-3 pt-3 pb-4">
            <p className="text-xs font-semibold tracking-[0.14em] text-ink-muted uppercase">Administration</p>
            <h2 className="mt-1 text-lg font-semibold">People & groups</h2>
          </div>
          <nav aria-label="Group navigation" className="space-y-1">
            <a
              href="#/admin/groups"
              aria-current={overview ? 'page' : undefined}
              className={`mb-3 flex items-center gap-2.5 rounded-lg px-3 py-3 text-sm font-semibold ${overview ? 'bg-brand-600 text-white' : 'text-ink-muted hover:bg-canvas'}`}
            >
              <Shield className="size-4" />
              All groups<span className="ml-auto text-xs">{groups?.length ?? '—'}</span>
            </a>
            {roots.map((group) => (
              <div key={group.id}>
                {navLink(group)}
                {children(group.id).map((child) => navLink(child, true))}
              </div>
            ))}
          </nav>
          <div className="mt-4 border-t border-line px-3 pt-4 pb-2">
            <p className="text-xs leading-5 text-ink-muted">
              Groups organize your people. Choose a group to view and manage its members.
            </p>
            <a href="#" className="mt-4 inline-flex items-center gap-1 text-xs font-semibold text-brand-600">
              <ChevronLeft className="size-3.5" />
              Back to schedule
            </a>
          </div>
        </aside>
        <div className="min-w-0">
          {error && (
            <div
              role="alert"
              className="mb-5 flex flex-wrap items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800"
            >
              <Alert className="size-4" />
              <span className="flex-1">Could not refresh groups. {error}</span>
              <button className="btn-secondary btn-sm" onClick={() => void loadGroups()}>
                Retry
              </button>
            </div>
          )}
          {!groups ? (
            !error && (
              <div
                role="status"
                className="card flex items-center justify-center gap-3 p-12 text-sm text-ink-muted"
              >
                <Spinner className="size-5" />
                Loading groups…
              </div>
            )
          ) : overview ? (
            <>
              <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="mb-2 text-xs font-semibold tracking-[0.14em] text-brand-600 uppercase">
                    Your organization
                  </p>
                  <h1 className="text-3xl font-semibold tracking-tight">Groups</h1>
                  <p className="mt-2 max-w-xl text-sm leading-6 text-ink-muted">
                    Give every team a place. Organize members, manage tenant access, and keep release
                    responsibilities clear.
                  </p>
                </div>
                <button className="btn-primary" onClick={() => setCreateOpen(true)}>
                  <Plus className="size-4" />
                  Create group
                </button>
              </div>
              <div className="mb-6 grid gap-3 sm:grid-cols-3">
                {[
                  ['Total groups', groups.length, 'System, tenant and custom groups'],
                  [
                    'Tenant groups',
                    groups.filter((g) => g.group_type === 'TENANT_SUBGROUP').length,
                    'Dedicated spaces for each tenant',
                  ],
                  [
                    'Unassigned members',
                    groups.find((g) => g.group_type === 'MEMBER_POOL')?.member_count ?? 0,
                    'Accounts waiting in Member Pool',
                  ],
                ].map(([label, count, caption]) => (
                  <div key={label} className="rounded-xl border border-line bg-white px-5 py-4">
                    <p className="text-xs font-medium text-ink-muted">{label}</p>
                    <p className="mt-2 text-2xl font-semibold tabular-nums">{count}</p>
                    <p className="mt-1 text-xs text-ink-muted">{caption}</p>
                  </div>
                ))}
              </div>
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-base font-semibold">Group directory</h2>
                <div className="relative w-full sm:w-72">
                  <Search className="pointer-events-none absolute top-3 left-3 size-4 text-ink-muted" />
                  <input
                    aria-label="Search groups"
                    className="field pl-9"
                    placeholder="Search groups…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </div>
              </div>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {filtered.map((group) => (
                  <GroupCard key={group.id} group={group} childCount={children(group.id).length} />
                ))}
              </div>
              {!filtered.length && (
                <div className="card p-10 text-center text-sm text-ink-muted">No groups match “{query}”.</div>
              )}
            </>
          ) : selected ? (
            <GroupDetail
              key={selected.id}
              group={selected}
              childGroups={children(selected.id)}
              isOwner={isOwner}
              onChanged={loadGroups}
            />
          ) : (
            <div className="card p-10 text-center">
              <h1 className="text-xl font-semibold">Group not found</h1>
              <p className="mt-2 text-sm text-ink-muted">
                This group may have been removed or the link is invalid.
              </p>
              <a href="#/admin/groups" className="btn-primary mt-5">
                View all groups
              </a>
            </div>
          )}
        </div>
      </div>
      <Modal
        open={createOpen}
        onClose={() => {
          if (!busy) setCreateOpen(false)
        }}
        title="Create a group"
        description="Create a working group for a team such as DBA or Azure."
      >
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void createGroup()
          }}
        >
          <label htmlFor="group-name" className="field-label">
            Group name
          </label>
          <input
            autoFocus
            required
            maxLength={120}
            id="group-name"
            className="field"
            placeholder="e.g. DBA Team"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <p className="mt-3 text-xs leading-5 text-ink-muted">
            Tenant groups are created from Tenant settings. Creating a custom group does not grant Release
            Manager access.
          </p>
          <div className="mt-5 flex justify-end gap-2">
            <button
              type="button"
              className="btn-secondary"
              disabled={busy}
              onClick={() => setCreateOpen(false)}
            >
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={busy || !newName.trim()}>
              {busy && <Spinner className="size-4" />}Create group
            </button>
          </div>
        </form>
      </Modal>
    </main>
  )
}

function GroupDetail({
  group,
  childGroups,
  isOwner,
  onChanged,
}: {
  group: AccessGroup
  childGroups: AccessGroup[]
  isOwner: boolean
  onChanged: () => Promise<void>
}) {
  const toast = useToast()
  const [detail, setDetail] = useState<AccessGroup | null>(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('all')
  const [addOpen, setAddOpen] = useState(false)
  const [removeTarget, setRemoveTarget] = useState<GroupMember | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [reload, setReload] = useState(0)
  useEffect(() => {
    let active = true
    setError('')
    api
      .getGroup(group.id)
      .then((result) => {
        if (active) setDetail(result)
      })
      .catch((e) => {
        if (active) setError(errorMessage(e))
      })
    return () => {
      active = false
    }
  }, [group.id, reload])
  const automatic = ['MEMBER_POOL', 'TENANTS'].includes(group.group_type)
  const canManage = !automatic && (group.group_type !== 'RELEASE_MANAGERS' || isOwner)
  const members = detail?.members ?? []
  const visible = members.filter(
    (member) =>
      `${member.full_name} ${member.username} ${member.email}`
        .toLowerCase()
        .includes(query.trim().toLowerCase()) &&
      (status === 'all' || member.is_active === (status === 'active')),
  )
  const visibleChildren = childGroups.filter((child) =>
    child.name.toLowerCase().includes(query.trim().toLowerCase()),
  )

  async function removeMember() {
    if (!removeTarget || busy) return
    setBusy(true)
    try {
      const updated = await api.removeGroupMember(group.id, removeTarget.id)
      setDetail(updated)
      setRemoveTarget(null)
      toast.success('Member removed', `${removeTarget.full_name} was removed from ${group.name}.`)
      await onChanged()
    } catch (e) {
      toast.error('Could not remove member', errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  async function deleteGroup() {
    if (busy) return
    setBusy(true)
    try {
      await api.deleteGroup(group.id)
      setDeleteOpen(false)
      window.location.hash = '#/admin/groups'
      toast.success('Group deleted')
      await onChanged()
    } catch (e) {
      toast.error('Could not delete group', errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <section className="overflow-hidden rounded-2xl border border-line bg-white shadow-card">
        <div className="h-1.5 bg-brand-600" />
        <div className="p-5 sm:p-7">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex min-w-0 items-start gap-4">
              <GroupIcon group={group} />
              <div className="min-w-0">
                <p className="text-xs font-semibold tracking-wide text-ink-muted uppercase">
                  {LABELS[group.group_type]}
                </p>
                <h1 className="mt-1 break-words text-2xl font-semibold tracking-tight sm:text-3xl">
                  {group.name}
                </h1>
              </div>
            </div>
            <div className="flex gap-2">
              {group.group_type === 'CUSTOM' && (
                <button
                  className="btn-secondary text-rose-600"
                  aria-label={`Delete ${group.name}`}
                  onClick={() => setDeleteOpen(true)}
                >
                  <Trash className="size-4" />
                  <span className="hidden sm:inline">Delete group</span>
                </button>
              )}
              {canManage && (
                <button className="btn-primary" disabled={!detail || busy} onClick={() => setAddOpen(true)}>
                  <Plus className="size-4" />
                  Add members
                </button>
              )}
            </div>
          </div>
          <p className="mt-4 max-w-2xl text-sm leading-6 text-ink-muted">
            {group.description || DESCRIPTIONS[group.group_type]}
          </p>
          <div className="mt-5 flex flex-wrap items-center gap-3 text-xs">
            <span
              className={`rounded-full px-2.5 py-1 font-medium ${group.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}
            >
              {group.is_active ? 'Active group' : 'Inactive group'}
            </span>
            <span className="text-ink-muted">
              {group.group_type === 'TENANTS'
                ? `${childGroups.length} tenant groups`
                : `${detail?.member_count ?? group.member_count} member${(detail?.member_count ?? group.member_count) === 1 ? '' : 's'}`}
            </span>
            <span className="text-ink-muted">
              {automatic
                ? 'Automatic membership'
                : canManage
                  ? 'Managed membership'
                  : 'Owner-managed membership'}
            </span>
          </div>
        </div>
      </section>
      {automatic || !canManage ? (
        <div className="my-5 flex items-start gap-3 rounded-xl border border-brand-100 bg-brand-50/60 p-4 text-sm leading-6 text-brand-700">
          <Shield className="mt-0.5 size-4 shrink-0" />
          <p>
            {group.group_type === 'MEMBER_POOL'
              ? 'Accounts appear here automatically when they have no working group. Open a tenant or working group and use Add members to assign them.'
              : group.group_type === 'TENANTS'
                ? 'Choose a tenant below to manage its members. Create or rename tenants in Release controls → Tenant settings.'
                : 'Only the organization owner can add or remove Release Managers. You can view the team’s membership here.'}
          </p>
        </div>
      ) : (
        <div className="h-5" />
      )}
      {group.group_type === 'TENANTS' ? (
        <section aria-label="Tenant groups">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">Tenant groups</h2>
            <input
              aria-label="Search tenant groups"
              className="field sm:max-w-72"
              placeholder="Search tenants…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {visibleChildren.map((child) => (
              <GroupCard key={child.id} group={child} childCount={0} />
            ))}
          </div>
          {!visibleChildren.length && (
            <div className="card p-10 text-center text-sm text-ink-muted">
              {query
                ? 'No tenants match your search.'
                : 'No tenant groups yet. Add a tenant in Tenant settings to get started.'}
            </div>
          )}
        </section>
      ) : (
        <section
          className="overflow-hidden rounded-2xl border border-line bg-white shadow-card"
          aria-label="Group members"
        >
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line p-5">
            <h2 className="flex items-center gap-2 text-base font-semibold">
              Members{' '}
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-ink-muted">
                {members.length}
              </span>
            </h2>
            <div className="flex w-full flex-wrap gap-2 sm:w-auto">
              <div className="relative min-w-0 flex-1 sm:w-64">
                <Search className="pointer-events-none absolute top-3 left-3 size-4 text-ink-muted" />
                <input
                  aria-label="Search members"
                  className="field pl-9"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search members…"
                />
              </div>
              <select
                aria-label="Filter member status"
                className="field w-auto"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              >
                <option value="all">All statuses</option>
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
              </select>
            </div>
          </div>
          {error ? (
            <div role="alert" className="p-8 text-center text-sm text-rose-700">
              Could not load members. {error}
              <button className="btn-secondary ml-3" onClick={() => setReload((n) => n + 1)}>
                Retry
              </button>
            </div>
          ) : !detail ? (
            <div role="status" className="flex justify-center gap-2 p-12 text-sm text-ink-muted">
              <Spinner className="size-4" />
              Loading members…
            </div>
          ) : !visible.length ? (
            <div className="px-5 py-14 text-center">
              <span className="mx-auto mb-4 grid size-12 place-items-center rounded-full bg-slate-50 text-ink-muted">
                <User className="size-6" />
              </span>
              <h3 className="font-semibold">{members.length ? 'No matching members' : 'No members yet'}</h3>
              <p className="mt-2 text-sm text-ink-muted">
                {members.length
                  ? 'Try another name or change the status filter.'
                  : automatic
                    ? 'Unassigned accounts will appear here automatically.'
                    : 'Add your first member to get this group started.'}
              </p>
              {canManage && !members.length && (
                <button className="btn-secondary mt-5" onClick={() => setAddOpen(true)}>
                  <Plus className="size-4" />
                  Add members
                </button>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-line bg-slate-50/70 text-xs text-ink-muted">
                  <tr>
                    <th scope="col" className="px-5 py-3 font-medium">
                      Member
                    </th>
                    <th scope="col" className="hidden px-5 py-3 font-medium md:table-cell">
                      Email address
                    </th>
                    <th scope="col" className="px-5 py-3 font-medium">
                      Status
                    </th>
                    {canManage && (
                      <th scope="col" className="px-5 py-3 text-right font-medium">
                        Action
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {visible.map((member) => (
                    <tr key={member.id} className="hover:bg-slate-50/60">
                      <td className="px-5 py-4">
                        <div className="flex items-center gap-3">
                          <span className="hidden size-9 shrink-0 place-items-center rounded-full bg-brand-50 text-xs font-semibold text-brand-700 sm:grid">
                            {initials(member.full_name)}
                          </span>
                          <div className="min-w-0">
                            <p className="break-words font-medium">{member.full_name}</p>
                            <p className="mt-0.5 text-xs text-ink-muted">@{member.username}</p>
                            <p className="mt-1 break-all text-xs text-ink-muted md:hidden">{member.email}</p>
                          </div>
                        </div>
                      </td>
                      <td className="hidden max-w-xs break-all px-5 py-4 text-ink-muted md:table-cell">
                        {member.email || '—'}
                      </td>
                      <td className="px-5 py-4">
                        <span
                          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${member.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}
                        >
                          <span
                            className={`size-1.5 rounded-full ${member.is_active ? 'bg-emerald-500' : 'bg-slate-400'}`}
                          />
                          {member.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      {canManage && (
                        <td className="px-5 py-4 text-right">
                          <button
                            className="rounded-md px-2 py-1 text-xs font-semibold text-rose-600 hover:bg-rose-50 disabled:opacity-40"
                            aria-label={`Remove ${member.full_name}`}
                            disabled={busy || member.is_owner}
                            onClick={() => setRemoveTarget(member)}
                          >
                            Remove
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {detail && !error && (
            <div className="border-t border-line px-5 py-3 text-xs text-ink-muted">
              Showing {visible.length} of {members.length} members
            </div>
          )}
        </section>
      )}
      {addOpen && detail && (
        <AddMembers
          group={detail}
          onClose={() => setAddOpen(false)}
          onAdded={async (updated) => {
            setDetail(updated)
            await onChanged()
          }}
        />
      )}
      <ConfirmationModal
        open={Boolean(removeTarget)}
        onClose={() => {
          if (!busy) setRemoveTarget(null)
        }}
        onConfirm={() => void removeMember()}
        busy={busy}
        title="Remove member?"
        description={`Remove ${removeTarget?.full_name ?? ''} from ${group.name}? Their account will remain available.`}
        note="Members without another working group return to Member Pool automatically."
        confirmLabel="Remove member"
        cancelLabel="Cancel"
      />
      <ConfirmationModal
        open={deleteOpen}
        onClose={() => {
          if (!busy) setDeleteOpen(false)
        }}
        onConfirm={() => void deleteGroup()}
        busy={busy}
        title="Delete group?"
        description={`Delete ${group.name}? Member accounts will be kept.`}
        note="Members without another working group return to Member Pool automatically."
        confirmLabel="Delete group"
        cancelLabel="Cancel"
      />
    </>
  )
}

function AddMembers({
  group,
  onClose,
  onAdded,
}: {
  group: AccessGroup
  onClose: () => void
  onAdded: (group: AccessGroup) => Promise<void>
}) {
  const toast = useToast()
  const [query, setQuery] = useState('')
  const [users, setUsers] = useState<ManagedUser[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState<number | null>(null)
  const [retry, setRetry] = useState(0)
  const [addedIds, setAddedIds] = useState<number[]>([])
  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    const timer = window.setTimeout(() => {
      api
        .listUsers(query.trim())
        .then((rows) => {
          if (active) setUsers(rows)
        })
        .catch((e) => {
          if (active) setError(errorMessage(e))
        })
        .finally(() => {
          if (active) setLoading(false)
        })
    }, 200)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [query, retry])
  const memberIds = new Set([...(group.members ?? []).map((member) => member.id), ...addedIds])
  const candidates = users.filter((user) => !user.is_owner && user.is_active && !memberIds.has(user.id))
  async function add(user: ManagedUser) {
    if (busyId !== null) return
    setBusyId(user.id)
    try {
      const updated = await api.addGroupMember(group.id, user.id)
      setAddedIds((ids) => [...ids, user.id])
      toast.success('Member added', `${user.full_name} joined ${group.name}.`)
      await onAdded(updated)
    } catch (e) {
      toast.error('Could not add member', errorMessage(e))
    } finally {
      setBusyId(null)
    }
  }
  return (
    <Modal
      open
      onClose={() => {
        if (busyId === null) onClose()
      }}
      size="md"
      title={`Add members to ${group.name}`}
      description="Find an active account by name, username or email."
      footer={
        <div className="flex items-center justify-between gap-3">
          <p role="status" className="text-xs text-ink-muted">
            {addedIds.length
              ? `${addedIds.length} member${addedIds.length === 1 ? '' : 's'} added`
              : 'Existing members are excluded.'}
          </p>
          <button className="btn-primary" onClick={onClose} disabled={busyId !== null}>
            Done
          </button>
        </div>
      }
    >
      <label className="sr-only" htmlFor="add-member-search">
        Search accounts
      </label>
      <div className="relative">
        <Search className="pointer-events-none absolute top-3 left-3 size-4 text-ink-muted" />
        <input
          autoFocus
          id="add-member-search"
          className="field pl-9"
          placeholder="Search accounts…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className="mt-4 max-h-[45vh] overflow-y-auto">
        {loading ? (
          <div role="status" className="flex justify-center gap-2 py-10 text-sm text-ink-muted">
            <Spinner className="size-4" />
            Finding accounts…
          </div>
        ) : error ? (
          <div role="alert" className="py-6 text-sm text-rose-700">
            {error}
            <button className="btn-secondary ml-2" onClick={() => setRetry((n) => n + 1)}>
              Retry
            </button>
          </div>
        ) : candidates.length ? (
          <ul className="divide-y divide-line">
            {candidates.map((user) => (
              <li key={user.id} className="flex items-center gap-3 py-3">
                <span className="grid size-9 shrink-0 place-items-center rounded-full bg-slate-100 text-xs font-semibold text-slate-600">
                  {initials(user.full_name)}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{user.full_name}</p>
                  <p className="truncate text-xs text-ink-muted">
                    @{user.username} · {user.email}
                  </p>
                </div>
                <button
                  className="btn-secondary btn-sm"
                  aria-label={`Add ${user.full_name}`}
                  disabled={busyId !== null}
                  onClick={() => void add(user)}
                >
                  {busyId === user.id ? <Spinner className="size-3.5" /> : <Plus className="size-3.5" />}Add
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="py-10 text-center text-sm text-ink-muted">
            No eligible accounts found. Try another search.
          </p>
        )}
      </div>
    </Modal>
  )
}
