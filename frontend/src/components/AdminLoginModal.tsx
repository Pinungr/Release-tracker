import { useEffect, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { AdminSession } from '../types'
import { Shield, Spinner } from './Icons'
import { Modal } from './Modal'
import { useToast } from './ToastNotification'

interface AdminLoginModalProps {
  open: boolean
  onClose: () => void
  onLoggedIn: (session: AdminSession) => void
}

export function AdminLoginModal({ open, onClose, onLoggedIn }: AdminLoginModalProps) {
  const toast = useToast()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setPassword('')
      setError(null)
    }
  }, [open])

  async function submit() {
    if (!username.trim() || !password) {
      setError('Enter both the username and password.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const session = await api.adminLogin(username.trim(), password)
      onLoggedIn(session)
      toast.success('Signed in as administrator.', session.username)
      onClose()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Sign in failed.')
    } finally {
      setPassword('')
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Administrator login"
      description="Only administrators sign in. Tenant users book deployments without an account."
      icon={<Shield className="size-5 text-brand-600" />}
      footer={
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" className="btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" form="admin-login" className="btn-primary" disabled={busy}>
            {busy ? <Spinner className="size-4" /> : null}
            Login
          </button>
        </div>
      }
    >
      <form
        id="admin-login"
        className="space-y-3"
        noValidate
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
      >
        <div>
          <label className="field-label" htmlFor="admin-username">
            Username
          </label>
          <input
            id="admin-username"
            className="field"
            value={username}
            autoComplete="username"
            onChange={(event) => setUsername(event.target.value)}
          />
        </div>
        <div>
          <label className="field-label" htmlFor="admin-password">
            Password
          </label>
          <input
            id="admin-password"
            type="password"
            className="field"
            value={password}
            autoComplete="current-password"
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>
        {error ? <p className="text-xs font-medium text-rose-600">{error}</p> : null}
      </form>
    </Modal>
  )
}
