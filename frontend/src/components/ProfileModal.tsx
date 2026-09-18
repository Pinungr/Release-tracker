import { useEffect, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { AuthUser } from '../types'
import { Shield, Spinner, User } from './Icons'
import { Modal } from './Modal'
import { useToast } from './ToastNotification'

interface ProfileModalProps {
  open: boolean
  onClose: () => void
  user: AuthUser
}

export function ProfileModal({ open, onClose, user }: ProfileModalProps) {
  const toast = useToast()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setCurrentPassword('')
    setNewPassword('')
    setConfirmPassword('')
    setError(null)
  }, [open])

  async function submit() {
    if (newPassword !== confirmPassword) {
      setError('New password and confirmation do not match.')
      return
    }
    if (newPassword.length < 8) {
      setError('Use at least 8 characters.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await api.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_new_password: confirmPassword,
      })
      toast.success('Password changed successfully.')
      onClose()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not change the password.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Profile"
      description="Your account details and password."
      icon={<User className="size-5 text-brand-600" />}
      footer={
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" className="btn-secondary" onClick={onClose} disabled={busy}>
            Close
          </button>
          <button type="submit" form="profile-form" className="btn-primary" disabled={busy}>
            {busy ? <Spinner className="size-4" /> : null}
            Change password
          </button>
        </div>
      }
    >
      <dl className="mb-4 grid grid-cols-[7rem_1fr] gap-x-4 gap-y-2 rounded-lg bg-canvas p-3 text-sm">
        <dt className="text-ink-muted">Name</dt>
        <dd className="font-medium text-ink">{user.full_name}</dd>
        <dt className="text-ink-muted">Username</dt>
        <dd className="font-medium text-ink">{user.username}</dd>
        <dt className="text-ink-muted">Email</dt>
        <dd className="font-medium text-ink">{user.email ?? '—'}</dd>
        <dt className="text-ink-muted">Role</dt>
        <dd>
          <span
            className={`badge ${
              user.role === 'ADMIN'
                ? 'bg-brand-50 text-brand-700 ring-1 ring-brand-100'
                : 'bg-slate-100 text-slate-600 ring-1 ring-slate-200'
            }`}
          >
            {user.role === 'ADMIN' ? <Shield className="size-3" /> : null}
            {user.role.replace('_', ' ')}
          </span>
        </dd>
      </dl>

      <form
        id="profile-form"
        className="space-y-3"
        noValidate
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
      >
        <div>
          <label className="field-label" htmlFor="profile-current">
            Current password
          </label>
          <input
            id="profile-current"
            type="password"
            className="field"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
          />
        </div>
        <div>
          <label className="field-label" htmlFor="profile-new">
            New password
          </label>
          <input
            id="profile-new"
            type="password"
            className="field"
            autoComplete="new-password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
          />
        </div>
        <div>
          <label className="field-label" htmlFor="profile-confirm">
            Confirm new password
          </label>
          <input
            id="profile-confirm"
            type="password"
            className="field"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
          />
        </div>
        {error ? <p className="text-xs font-medium text-rose-600">{error}</p> : null}
      </form>
    </Modal>
  )
}
