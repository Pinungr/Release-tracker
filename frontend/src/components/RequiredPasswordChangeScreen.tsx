import { useState } from 'react'
import { api, ApiError } from '../services/api'
import type { AuthUser } from '../types'
import { Shield, Spinner } from './Icons'

interface RequiredPasswordChangeScreenProps {
  user: AuthUser
  onChanged: () => Promise<void>
  onLogout: () => void
}

export function RequiredPasswordChangeScreen({
  user,
  onChanged,
  onLogout,
}: RequiredPasswordChangeScreenProps) {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setError(null)
    if (newPassword.length < 8) {
      setError('Use at least 8 characters for the new password.')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('New password and confirmation do not match.')
      return
    }
    setBusy(true)
    try {
      await api.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_new_password: confirmPassword,
      })
      await onChanged()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not change the password.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-dvh place-items-center bg-canvas px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-3">
          <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-brand-600 text-white shadow-sm">
            <Shield className="size-5" />
          </span>
          <div>
            <h1 className="text-lg leading-tight font-semibold text-ink">Password change required</h1>
            <p className="text-sm text-ink-muted">
              {user.full_name}, the Owner or a Release Manager reset your password. Set a new password before using the scheduler.
            </p>
          </div>
        </div>

        <div className="card p-6">
          <form
            className="space-y-4"
            noValidate
            onSubmit={(event) => {
              event.preventDefault()
              void submit()
            }}
          >
            <div>
              <label className="field-label" htmlFor="forced-current">Temporary/current password</label>
              <input
                id="forced-current"
                type="password"
                className="field"
                autoComplete="current-password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
              />
            </div>
            <div>
              <label className="field-label" htmlFor="forced-new">New password</label>
              <input
                id="forced-new"
                type="password"
                className="field"
                autoComplete="new-password"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
              />
            </div>
            <div>
              <label className="field-label" htmlFor="forced-confirm">Confirm new password</label>
              <input
                id="forced-confirm"
                type="password"
                className="field"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
              />
            </div>

            {error ? <p className="text-xs font-medium text-rose-600">{error}</p> : null}

            <button type="submit" className="btn-primary w-full" disabled={busy}>
              {busy ? <Spinner className="size-4" /> : <Shield className="size-4" />}
              Change password and continue
            </button>
          </form>

          <button type="button" className="btn-ghost mt-3 w-full" onClick={onLogout} disabled={busy}>
            Sign out
          </button>
        </div>
      </div>
    </div>
  )
}
