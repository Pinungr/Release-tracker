import { useState } from 'react'
import { api, ApiError } from '../services/api'
import type { AuthSession } from '../types'
import { Shield, Spinner, User } from './Icons'
import { useToast } from './ToastNotification'

interface SignInScreenProps {
  onSignedIn: (session: AuthSession) => void
}

type Mode = 'login' | 'signup'

const EMPTY = {
  full_name: '',
  username_or_email: '',
  username: '',
  email: '',
  password: '',
  confirm_password: '',
}

/**
 * The gate in front of the whole application. Nothing is visible until a
 * person signs in: what they may then do comes from their stored role, never
 * from anything this screen decides.
 */
export function SignInScreen({ onSignedIn }: SignInScreenProps) {
  const toast = useToast()
  const [mode, setMode] = useState<Mode>('login')
  const [values, setValues] = useState(EMPTY)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function switchMode(next: Mode) {
    setMode(next)
    setError(null)
    setValues((current) => ({ ...current, password: '', confirm_password: '' }))
  }

  async function submit() {
    setError(null)
    if (mode === 'signup' && values.password !== values.confirm_password) {
      setError('Password and confirmation do not match.')
      return
    }
    setBusy(true)
    try {
      if (mode === 'signup') {
        await api.register({
          full_name: values.full_name,
          username: values.username,
          email: values.email,
          password: values.password,
          confirm_password: values.confirm_password,
        })
        toast.success('Account created.', 'Sign in with your new account.')
        setMode('login')
        setValues((current) => ({
          ...EMPTY,
          username_or_email: current.username,
        }))
      } else {
        const session = await api.login(values.username_or_email.trim(), values.password)
        onSignedIn(session)
        toast.success('Signed in.', session.user.full_name)
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Request failed.')
    } finally {
      setBusy(false)
    }
  }

  function field(
    key: keyof typeof values,
    label: string,
    type = 'text',
    autoComplete?: string,
  ) {
    return (
      <div>
        <label className="field-label" htmlFor={`auth-${key}`}>
          {label}
        </label>
        <input
          id={`auth-${key}`}
          className="field"
          type={type}
          value={values[key]}
          autoComplete={autoComplete}
          onChange={(event) =>
            setValues((current) => ({ ...current, [key]: event.target.value }))
          }
        />
      </div>
    )
  }

  return (
    <div className="grid flex-1 place-items-center bg-canvas px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-3">
          <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-brand-600 text-sm font-bold text-white shadow-sm">
            PD
          </span>
          <div>
            <h1 className="text-lg leading-tight font-semibold text-ink">
              Production Deployment Scheduler
            </h1>
            <p className="text-sm text-ink-muted">
              {mode === 'login'
                ? 'Sign in to view and schedule production changes.'
                : 'Create an account to start scheduling changes.'}
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
            {mode === 'signup' ? (
              <>
                {field('full_name', 'Full name', 'text', 'name')}
                {field('username', 'Username', 'text', 'username')}
                {field('email', 'Email', 'email', 'email')}
                {field('password', 'Password', 'password', 'new-password')}
                {field('confirm_password', 'Confirm password', 'password', 'new-password')}
              </>
            ) : (
              <>
                {field('username_or_email', 'Username / Email', 'text', 'username')}
                {field('password', 'Password', 'password', 'current-password')}
              </>
            )}

            {error ? (
              <p className="whitespace-pre-line text-xs font-medium text-rose-600">{error}</p>
            ) : null}

            <button type="submit" className="btn-primary w-full" disabled={busy}>
              {busy ? <Spinner className="size-4" /> : <User className="size-4" />}
              {mode === 'login' ? 'Sign in' : 'Create account'}
            </button>
          </form>

          <div className="mt-5 border-t border-line pt-4 text-center text-sm text-ink-muted">
            {mode === 'login' ? (
              <>
                Don&apos;t have an account?{' '}
                <button
                  type="button"
                  className="font-semibold text-brand-700 hover:text-brand-900"
                  onClick={() => switchMode('signup')}
                >
                  Sign up
                </button>
              </>
            ) : (
              <>
                Already have an account?{' '}
                <button
                  type="button"
                  className="font-semibold text-brand-700 hover:text-brand-900"
                  onClick={() => switchMode('login')}
                >
                  Sign in
                </button>
              </>
            )}
          </div>
        </div>

        <p className="mt-5 flex items-start gap-2 text-xs text-ink-muted">
          <Shield className="mt-0.5 size-4 shrink-0" />
          <span>
            You sign in as a person, not as a tenant. Choose the tenant when you schedule each
            change — one account can schedule for many tenants.
          </span>
        </p>
      </div>
    </div>
  )
}
