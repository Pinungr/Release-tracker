import { useEffect, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { BookingDetail, SlotOption } from '../types'
import { formatDate } from '../utils/dates'
import { Alert, Calendar, Spinner } from './Icons'
import { Modal } from './Modal'
import { useToast } from './ToastNotification'

interface RescheduleModalProps {
  open: boolean
  onClose: () => void
  booking: BookingDetail | null
  /** Admin-only fallback for emergency changes, which carry no slot. */
  onMoveEmergency?: (booking: BookingDetail) => void
  onDone: () => void
}

function keyOf(option: SlotOption): string {
  return `${option.deployment_date}#${option.slot_number}`
}

/**
 * Picks a destination from the slots the server says this caller may actually
 * book. Nothing here decides eligibility: the list already excludes holidays,
 * frozen dates, disabled slots, taken slots and weeks at the tenant limit, and
 * the move is validated again on submit.
 */
export function RescheduleModal({
  open,
  onClose,
  booking,
  onMoveEmergency,
  onDone,
}: RescheduleModalProps) {
  const toast = useToast()
  const [options, setOptions] = useState<SlotOption[]>([])
  const [selected, setSelected] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || !booking || booking.is_emergency) return
    let cancelled = false
    setLoading(true)
    setError(null)
    setSelected('')
    api
      .getRescheduleOptions(booking.id)
      .then((next) => {
        if (cancelled) return
        setOptions(next)
        if (next.length) setSelected(keyOf(next[0]))
      })
      .catch((caught) => {
        if (cancelled) return
        setOptions([])
        setError(caught instanceof ApiError ? caught.message : 'Could not load available slots.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, booking?.id, booking?.is_emergency, booking?.deployment_date, booking?.slot_number])

  async function confirm() {
    if (!booking) return
    const target = options.find((option) => keyOf(option) === selected)
    if (!target) {
      setError('Select one of the available slots.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await api.rescheduleBooking(booking.id, target.deployment_date, target.slot_number)
      toast.success(
        'Deployment rescheduled.',
        `${booking.booking_reference} · ${formatDate(target.deployment_date)} · ${target.slot_name}`,
      )
      onDone()
      onClose()
    } catch (caught) {
      // A slot lost between the picker and the confirmation leaves the
      // original booking exactly as it was; re-reading restores the list.
      const message = caught instanceof ApiError ? caught.message : 'Could not reschedule this booking.'
      setError(message)
      if (caught instanceof ApiError && caught.status === 409 && booking) {
        api
          .getRescheduleOptions(booking.id)
          .then((next) => {
            setOptions(next)
            setSelected(next.length ? keyOf(next[0]) : '')
          })
          .catch(() => undefined)
      }
    } finally {
      setBusy(false)
    }
  }

  if (!booking) return null

  // Emergency changes are a per-date queue rather than a slot, so there are no
  // "next available slots" to offer. Administrators move them by date instead.
  if (booking.is_emergency) {
    return (
      <Modal
        open={open}
        onClose={onClose}
        title="Move emergency change"
        description="Emergency changes occupy a date's queue, not a numbered slot."
        size="md"
        footer={
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-secondary" onClick={onClose}>
              Close
            </button>
            {onMoveEmergency ? (
              <button
                type="button"
                className="btn-primary"
                onClick={() => {
                  onClose()
                  onMoveEmergency(booking)
                }}
              >
                <Calendar className="size-4" />
                Choose a new date
              </button>
            ) : null}
          </div>
        }
      >
        <p className="text-sm text-ink-muted">
          {onMoveEmergency
            ? 'Pick the new deployment date for this emergency change.'
            : 'Only the Owner or a Release Manager can move an emergency change.'}
        </p>
      </Modal>
    )
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Reschedule deployment"
      description={
        <>
          Currently {formatDate(booking.deployment_date)} · {booking.slot_label}. The booking keeps
          its reference, documents and every other detail — only the date and slot move.
        </>
      }
      size="md"
      footer={
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-secondary" onClick={onClose} disabled={busy}>
            Keep current slot
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={() => void confirm()}
            disabled={busy || loading || !selected}
          >
            {busy ? <Spinner className="size-4" /> : null}
            Reschedule to this slot
          </button>
        </div>
      }
    >
      <h3 className="field-label mb-2">Next available slots</h3>

      {loading ? (
        <div className="flex items-center justify-center gap-3 py-10 text-sm text-ink-muted">
          <Spinner className="size-5" />
          Finding available slots…
        </div>
      ) : options.length === 0 ? (
        <div className="flex items-start gap-3 rounded-xl border border-line bg-canvas p-4">
          <Alert className="mt-0.5 size-5 shrink-0 text-ink-muted" />
          <p className="text-sm text-ink-muted">
            No eligible slot is available for this booking right now. Holidays, frozen dates and
            your tenant's weekly limit all reduce what can be offered.
          </p>
        </div>
      ) : (
        <ul className="max-h-80 space-y-1.5 overflow-y-auto pr-1">
          {options.map((option) => {
            const key = keyOf(option)
            const active = key === selected
            return (
              <li key={key}>
                <label
                  className={`flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 text-sm transition-colors ${
                    active
                      ? 'border-brand-300 bg-brand-50/60 ring-1 ring-brand-200'
                      : 'border-line bg-surface hover:bg-canvas'
                  }`}
                >
                  <input
                    type="radio"
                    name="reschedule-slot"
                    className="shrink-0"
                    value={key}
                    checked={active}
                    onChange={() => setSelected(key)}
                  />
                  <span className="w-28 shrink-0 font-semibold tnum text-ink">
                    {option.weekday.slice(0, 3)} {option.date_label}
                  </span>
                  <span className="w-20 shrink-0 text-ink">{option.slot_name}</span>
                  <span className="min-w-0 truncate tnum text-ink-muted">{option.time_label}</span>
                </label>
              </li>
            )
          })}
        </ul>
      )}

      {error ? <p className="mt-3 text-xs font-medium text-rose-600">{error}</p> : null}
    </Modal>
  )
}
