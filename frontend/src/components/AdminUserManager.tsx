import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { ManagedUser } from '../types'
import { formatTimestamp } from '../utils/dates'
import { Check, Search, Shield, Spinner, User } from './Icons'
import { ConfirmationModal, Modal } from './Modal'
import { useToast } from './ToastNotification'

/**
 * Administrator view of the one users table. An administrator can change a
 * role, activate/deactivate, and set a new password — but never sees an
 * existing password or its hash, because the API does not return either.
 *
 * Administrators manage tenant users. Acting on an account that is already an
 * ADMIN is reserved for the owner, and the owner account is never a valid
 * target. Hiding the buttons here is only a convenience: the API enforces the
 * same rules and is the source of truth.
 */
export function AdminUserManager({
  timezone,
  currentUserId,
  isOwner,
}: {
  timezone: string
  currentUserId: number
  isOwner: boolean
}) {
  const toast = useToast()
  const [users, setUsers] = useState<ManagedUser[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [busyId, setBusyId] = useState<number | null>(null)
  const [resetTarget, setResetTarget] = useState<ManagedUser | null>(null)
  const [confirmRole, setConfirmRole] = useState<ManagedUser | null>(null)

  const load = useCallback((term = '') => {
    setError(null)
    api
      .listUsers(term.trim() || undefined)
      .then(setUsers)
      .catch((caught) => {
        setUsers([])
        setError(caught instanceof ApiError ? caught.message : 'Could not load users.')
      })
  }, [])

  useEffect(() => load(), [load])

  async function act(user: ManagedUser, run: () => Promise<unknown>, success: string) {
    setBusyId(user.id)
    try {
      await run()
      load(search)
      toast.success(success, user.username)
    } catch (caught) {
      toast.error('Could not update the user', caught instanceof ApiError ? caught.message : '')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section>
      <h3 className="text-sm font-semibold text-ink">User management</h3>
      <p className="mt-0.5 text-xs text-ink-muted">
        Everyone signs in through the same login; the role below is what grants administrator
        access.
      </p>

      <form
        className="mt-4 mb-4 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          load(search)
        }}
      >
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-muted" />
          <input
            className="field pl-9"
            placeholder="Search name, username or email"
            aria-label="Search users"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <button type="submit" className="btn-secondary">
          Search
        </button>
      </form>

      {error ? <p className="mb-3 text-sm text-rose-600">{error}</p> : null}

      {!users ? (
        <div className="flex items-center gap-2 py-8 text-sm text-ink-muted">
          <Spinner className="size-4" />
          Loading users…
        </div>
      ) : users.length === 0 ? (
        <p className="text-sm text-ink-muted">No users match that search.</p>
      ) : (
        <ul className="space-y-2">
          {users.map((user) => {
            // Mirrors _assert_may_manage on the server.
            const manageable =
              !user.is_owner && user.id !== currentUserId && (isOwner || user.role !== 'ADMIN')
            const canPromote = isOwner
            return (
            <li key={user.id} className="rounded-lg border border-line p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-ink">{user.full_name}</span>
                <span className="text-xs text-ink-muted">@{user.username}</span>
                <span
                  className={`badge ${
                    user.role === 'ADMIN'
                      ? 'bg-brand-50 text-brand-700 ring-1 ring-brand-100'
                      : 'bg-slate-100 text-slate-600 ring-1 ring-slate-200'
                  }`}
                >
                  {user.role === 'ADMIN' ? <Shield className="size-3" /> : <User className="size-3" />}
                  {user.role.replace('_', ' ')}
                </span>
                <span
                  className={`badge ${
                    user.is_active
                      ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100'
                      : 'bg-slate-100 text-slate-500 ring-1 ring-slate-200'
                  }`}
                >
                  {user.is_active ? 'Active' : 'Inactive'}
                </span>
                {user.is_owner ? (
                  <span className="tooltip-host">
                    <span className="badge bg-violet-50 text-violet-700 ring-1 ring-violet-200">
                      <Shield className="size-3" />
                      Owner
                    </span>
                    <span className="tooltip">
                      The protected owner account. It cannot be demoted, deactivated or reset by
                      anyone, and only the owner can manage other administrators.
                    </span>
                  </span>
                ) : null}
                {user.must_change_password ? (
                  <span className="badge bg-amber-50 text-amber-800 ring-1 ring-amber-200">
                    Must change password
                  </span>
                ) : null}
              </div>

              <p className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-ink-muted">
                <span>{user.email}</span>
                <span>Created {formatTimestamp(user.created_at, timezone)}</span>
              </p>

              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                {manageable ? (
                  <>
                    {user.role === 'ADMIN' || canPromote ? (
                      <button
                        type="button"
                        className="btn-secondary btn-sm"
                        disabled={busyId === user.id}
                        onClick={() => setConfirmRole(user)}
                      >
                        {user.role === 'ADMIN' ? 'Demote to tenant user' : 'Promote to admin'}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="btn-ghost btn-sm"
                      disabled={busyId === user.id}
                      onClick={() =>
                        void act(
                          user,
                          () => api.setUserActive(user.id, !user.is_active),
                          user.is_active ? 'User deactivated.' : 'User activated.',
                        )
                      }
                    >
                      {user.is_active ? 'Deactivate' : 'Activate'}
                    </button>
                    <button
                      type="button"
                      className="btn-ghost btn-sm"
                      disabled={busyId === user.id}
                      onClick={() => setResetTarget(user)}
                    >
                      Reset password
                    </button>
                  </>
                ) : (
                  <p className="text-xs text-ink-muted">
                    {user.is_owner
                      ? 'The owner account is protected. Its credentials are managed by the owner alone.'
                      : user.id === currentUserId
                        ? 'You cannot manage your own account here. Change your password from your profile.'
                        : 'Only the owner can manage an administrator account.'}
                  </p>
                )}
              </div>
            </li>
            )
          })}
        </ul>
      )}

      <ConfirmationModal
        open={confirmRole !== null}
        onClose={() => setConfirmRole(null)}
        onConfirm={() => {
          const target = confirmRole
          if (!target) return
          setConfirmRole(null)
          void act(
            target,
            () => api.setUserRole(target.id, target.role === 'ADMIN' ? 'TENANT_USER' : 'ADMIN'),
            'Role updated.',
          )
        }}
        title={confirmRole?.role === 'ADMIN' ? 'Demote this administrator?' : 'Promote to administrator?'}
        facts={
          confirmRole
            ? [
                { label: 'User', value: confirmRole.full_name },
                { label: 'Username', value: confirmRole.username },
                { label: 'Current role', value: confirmRole.role.replace('_', ' ') },
              ]
            : []
        }
        note={
          confirmRole?.role === 'ADMIN'
            ? 'They will lose administrator access on their very next request.'
            : 'They will gain full administrator access immediately, including emergency changes and overrides.'
        }
        confirmLabel={confirmRole?.role === 'ADMIN' ? 'Demote' : 'Promote'}
        cancelLabel="Keep current role"
        destructive={confirmRole?.role === 'ADMIN'}
      />

      {resetTarget ? (
        <ResetPasswordModal
          user={resetTarget}
          onClose={() => setResetTarget(null)}
          onDone={() => {
            setResetTarget(null)
            load(search)
          }}
        />
      ) : null}
    </section>
  )
}

function ResetPasswordModal({
  user,
  onClose,
  onDone,
}: {
  user: ManagedUser
  onClose: () => void
  onDone: () => void
}) {
  const toast = useToast()
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (password !== confirm) {
      setError('Password and confirmation do not match.')
      return
    }
    if (password.length < 8) {
      setError('Use at least 8 characters.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await api.resetUserPassword(user.id, password, confirm)
      toast.success('Password reset.', `${user.username} must change it at next sign-in.`)
      onDone()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not reset the password.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title="Reset password"
      description={`Set a new password for ${user.full_name} (@${user.username}).`}
      icon={<Check className="size-5 text-brand-600" />}
      footer={
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" className="btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" form="reset-password" className="btn-primary" disabled={busy}>
            {busy ? <Spinner className="size-4" /> : null}
            Set password
          </button>
        </div>
      }
    >
      <form
        id="reset-password"
        className="space-y-3"
        noValidate
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
      >
        <div>
          <label className="field-label" htmlFor="reset-new">
            New password
          </label>
          <input
            id="reset-new"
            type="password"
            className="field"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>
        <div>
          <label className="field-label" htmlFor="reset-confirm">
            Confirm password
          </label>
          <input
            id="reset-confirm"
            type="password"
            className="field"
            autoComplete="new-password"
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
          />
        </div>
        {error ? <p className="text-xs font-medium text-rose-600">{error}</p> : null}
        <p className="text-xs text-ink-muted">
          The server hashes this immediately. Existing passwords are never visible to anyone,
          including administrators.
        </p>
      </form>
    </Modal>
  )
}
