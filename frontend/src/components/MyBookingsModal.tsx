import { useEffect, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { BookingDetail, OwnerCredentials } from '../types'
import { formatDate } from '../utils/dates'
import { Calendar, Search, Spinner, User } from './Icons'
import { Modal } from './Modal'
import { BookingStatusBadge, LockBadge } from './StatusBadge'
import { useToast } from './ToastNotification'

interface MyBookingsModalProps {
  open: boolean
  onClose: () => void
  onFound: (bookings: BookingDetail[], credentials: OwnerCredentials) => void
  onOpenBooking: (bookingId: number) => void
}

export function MyBookingsModal({ open, onClose, onFound, onOpenBooking }: MyBookingsModalProps) {
  const toast = useToast()
  const [email, setEmail] = useState('')
  const [pin, setPin] = useState('')
  const [busy, setBusy] = useState(false)
  const [results, setResults] = useState<BookingDetail[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setResults(null)
      setError(null)
      setPin('')
    }
  }, [open])

  async function submit() {
    if (!/^\d{6}$/.test(pin)) {
      setError('The booking PIN must be exactly 6 digits.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const credentials: OwnerCredentials = { requester_email: email.trim(), booking_pin: pin }
      const bookings = await api.myBookings(credentials)
      setResults(bookings)
      onFound(bookings, credentials)
      if (bookings.length === 0) {
        setError('No bookings match that email and PIN.')
      } else {
        toast.success(
          `${bookings.length} booking${bookings.length === 1 ? '' : 's'} found.`,
          'Your bookings are highlighted on the board.',
        )
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Lookup failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="md"
      title="Find my bookings"
      description="Because tenant users do not have accounts, enter the requester email and the PIN you chose when booking."
      icon={<User className="size-5 text-brand-600" />}
      footer={
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" className="btn-secondary" onClick={onClose} disabled={busy}>
            Close
          </button>
          <button type="submit" form="my-bookings" className="btn-primary" disabled={busy}>
            {busy ? <Spinner className="size-4" /> : <Search className="size-4" />}
            Find bookings
          </button>
        </div>
      }
    >
      <form
        id="my-bookings"
        className="space-y-3"
        noValidate
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="field-label" htmlFor="mine-email">
              Requester email
            </label>
            <input
              id="mine-email"
              type="email"
              className="field"
              value={email}
              autoComplete="email"
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
            />
          </div>
          <div>
            <label className="field-label" htmlFor="mine-pin">
              Booking PIN
            </label>
            <input
              id="mine-pin"
              type="password"
              inputMode="numeric"
              maxLength={6}
              className="field tnum tracking-[0.4em]"
              value={pin}
              onChange={(event) => setPin(event.target.value.replace(/\D/g, '').slice(0, 6))}
              placeholder="······"
            />
          </div>
        </div>
        {error ? <p className="text-xs font-medium text-rose-600">{error}</p> : null}
      </form>

      {results && results.length > 0 ? (
        <ul className="mt-4 max-h-72 space-y-2 overflow-y-auto">
          {results.map((booking) => (
            <li key={booking.id}>
              <button
                type="button"
                onClick={() => {
                  onOpenBooking(booking.id)
                  onClose()
                }}
                className="w-full rounded-lg border border-line p-3 text-left transition-colors hover:border-brand-100 hover:bg-brand-50/50"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-ink">{booking.tenant_name}</span>
                  <span className="text-xs tnum text-ink-muted">{booking.booking_reference}</span>
                  <span className="ml-auto flex items-center gap-1.5">
                    <BookingStatusBadge status={booking.status} />
                    {booking.is_locked && booking.status !== 'CANCELLED' ? <LockBadge /> : null}
                  </span>
                </div>
                <p className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-ink-muted">
                  <span className="inline-flex items-center gap-1">
                    <Calendar className="size-3.5" />
                    {formatDate(booking.deployment_date)}
                  </span>
                  <span>
                    {booking.slot_label} · {booking.slot_time}
                  </span>
                  <span>{booking.jira_change}</span>
                  <span>
                    {booking.documents.provided_required}/{booking.documents.total_required} documents
                  </span>
                </p>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </Modal>
  )
}
