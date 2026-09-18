import { useEffect, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { BookingDetail, OwnerCredentials } from '../types'
import { Shield, Spinner } from './Icons'
import { Modal } from './Modal'
import { useToast } from './ToastNotification'

interface OwnerVerificationModalProps {
  open: boolean
  onClose: () => void
  bookingId: number | null
  reason: string
  onVerified: (booking: BookingDetail, credentials: OwnerCredentials, manageToken: string) => void
}

/**
 * Exchanges the requester email + PIN for the unredacted booking and a manage
 * token. Verification happens on the backend; nothing is trusted client side.
 */
export function OwnerVerificationModal({
  open,
  onClose,
  bookingId,
  reason,
  onVerified,
}: OwnerVerificationModalProps) {
  const toast = useToast()
  const [email, setEmail] = useState('')
  const [pin, setPin] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setEmail('')
      setPin('')
      setError(null)
    }
  }, [open, bookingId])

  async function submit() {
    if (!bookingId) return
    if (!/^\d{6}$/.test(pin)) {
      setError('The booking PIN must be exactly 6 digits.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const credentials: OwnerCredentials = { requester_email: email.trim(), booking_pin: pin }
      const result = await api.verifyOwner(bookingId, credentials)
      onVerified(result.booking, credentials, result.manage_token)
      toast.success('Ownership verified.')
      onClose()
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : 'Verification failed.'
      setError(message)
      if (caught instanceof ApiError && caught.status === 429) toast.error('Too many attempts', message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Verify booking ownership"
      description={reason}
      icon={<Shield className="size-5 text-brand-600" />}
      footer={
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" className="btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" form="owner-verify" className="btn-primary" disabled={busy}>
            {busy ? <Spinner className="size-4" /> : null}
            Verify
          </button>
        </div>
      }
    >
      <form
        id="owner-verify"
        className="space-y-3"
        noValidate
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
      >
        <div>
          <label className="field-label" htmlFor="verify-email">
            Requester email
          </label>
          <input
            id="verify-email"
            type="email"
            className="field"
            value={email}
            autoComplete="email"
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@example.com"
          />
        </div>
        <div>
          <label className="field-label" htmlFor="verify-pin">
            Booking PIN
          </label>
          <input
            id="verify-pin"
            type="password"
            inputMode="numeric"
            maxLength={6}
            className="field tnum tracking-[0.4em]"
            value={pin}
            autoComplete="one-time-code"
            onChange={(event) => setPin(event.target.value.replace(/\D/g, '').slice(0, 6))}
            placeholder="······"
          />
        </div>
        {error ? <p className="text-xs font-medium text-rose-600">{error}</p> : null}
      </form>
    </Modal>
  )
}
