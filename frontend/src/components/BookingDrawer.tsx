import { useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../services/api'
import type {
  BookingCreated,
  BookingDetail,
  BookingFormValues,
  DayView,
  PublicSettings,
  SlotView,
  Tenant,
} from '../types'
import {
  BookingForm,
  EMPTY_BOOKING_VALUES,
  toBookingPayload,
  validateBookingForm,
  valuesFromBooking,
  type BookingFormErrors,
} from './BookingForm'
import { DocumentReadinessPanel } from './DocumentReadiness'
import { DocumentUploader } from './DocumentUploader'
import { Drawer } from './Drawer'
import { Alert, Calendar, Check, Clock, Siren, Spinner } from './Icons'
import { useToast } from './ToastNotification'
import { formatDate, weekdayOf } from '../utils/dates'

export interface CreateTarget {
  day: DayView
  slot: SlotView | null
  isEmergency: boolean
}

interface BookingDrawerProps {
  open: boolean
  onClose: () => void
  settings: PublicSettings
  isAdmin: boolean
  /**
   * Present when creating. A normal change carries the chosen slot; an
   * emergency change carries none, because it joins the date's queue.
   */
  createTarget: CreateTarget | null
  /** Present when editing an existing booking. */
  editBooking: BookingDetail | null
  onSaved: () => void
}

export function BookingDrawer({
  open,
  onClose,
  settings,
  isAdmin,
  createTarget,
  editBooking,
  onSaved,
}: BookingDrawerProps) {
  const toast = useToast()
  const mode = editBooking ? 'edit' : 'create'
  const isEmergency = editBooking?.is_emergency ?? createTarget?.isEmergency ?? false

  const [values, setValues] = useState<BookingFormValues>(EMPTY_BOOKING_VALUES)
  const [errors, setErrors] = useState<BookingFormErrors>({})
  const [saving, setSaving] = useState(false)
  const [created, setCreated] = useState<BookingCreated | null>(null)
  const [tenants, setTenants] = useState<Tenant[]>([])

  // Reset only when the drawer opens or switches booking. `settings` is
  // deliberately not a dependency: it is a fresh object after every schedule
  // refresh, which would otherwise wipe the form (and the success view) the
  // moment a booking is saved.
  const technologyDefault = settings.technologies[0] ?? 'Other'
  const technologyRef = useRef(technologyDefault)
  technologyRef.current = technologyDefault

  useEffect(() => {
    if (!open) return
    setErrors({})
    setCreated(null)
    setValues(
      editBooking
        ? valuesFromBooking(editBooking)
        : { ...EMPTY_BOOKING_VALUES, technology: technologyRef.current },
    )
  }, [open, editBooking])

  useEffect(() => {
    if (!open) return
    api.getActiveTenants().then(setTenants).catch(() => setTenants([]))
  }, [open])

  const heading = useMemo(() => {
    if (created) return isEmergency ? 'Emergency change queued' : 'Deployment slot booked'
    if (editBooking) return `Edit ${editBooking.booking_reference}`
    if (isEmergency) return 'Book emergency change'
    return 'Book production deployment'
  }, [created, editBooking, isEmergency])

  const slotContext = createTarget
    ? {
        weekday: createTarget.day.weekday,
        dateLabel: createTarget.day.date_label,
        slotName: createTarget.slot?.name ?? 'Emergency queue',
        timeLabel: createTarget.slot?.time_label ?? 'No fixed slot',
      }
    : editBooking
      ? {
          weekday: weekdayOf(editBooking.deployment_date),
          dateLabel: formatDate(editBooking.deployment_date),
          slotName: editBooking.slot_label,
          timeLabel: editBooking.slot_time,
        }
      : null

  function update<K extends keyof BookingFormValues>(field: K, value: BookingFormValues[K]) {
    setValues((current) => ({ ...current, [field]: value }))
    setErrors((current) => ({ ...current, [field]: undefined }))
  }

  async function submit() {
    const found = validateBookingForm(values, { isEmergency })
    setErrors(found)
    if (Object.keys(found).length > 0) {
      toast.error('Please correct the highlighted fields.')
      return
    }

    setSaving(true)
    try {
      if (mode === 'create' && createTarget) {
        const payload = toBookingPayload(values, {
          deployment_date: createTarget.day.day,
          slot_number: createTarget.slot?.slot_number ?? null,
          is_emergency: isEmergency,
          override_weekly_limit: isAdmin ? values.override_weekly_limit : false,
          override_reason: isAdmin ? values.override_reason || null : null,
        })
        const result = await api.createBooking(payload)
        setCreated(result)
        onSaved()
        toast.success(
          isEmergency ? 'Emergency change queued.' : 'Deployment slot booked successfully.',
          `Reference ${result.booking.booking_reference}`,
        )
      } else if (editBooking) {
        const payload = toBookingPayload(values, {
          deployment_date: editBooking.deployment_date,
          slot_number: editBooking.slot_number,
          override_weekly_limit: isAdmin ? values.override_weekly_limit : false,
          override_reason: isAdmin ? values.override_reason || null : null,
        })
        await api.updateBooking(editBooking.id, payload)
        onSaved()
        toast.success('Booking updated successfully.')
        onClose()
      }
    } catch (error) {
      const message = error instanceof ApiError ? error.message : 'Something went wrong.'
      if (error instanceof ApiError && error.status === 423) toast.locked('This booking is locked', message)
      else if (error instanceof ApiError && error.status === 409) toast.error('Not available', message)
      else toast.error('Could not save the booking', message)
    } finally {
      setSaving(false)
    }
  }

  const formId = 'booking-form'

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={heading}
      width="xl"
      eyebrow={
        isEmergency ? (
          <span className="badge bg-orange-100 text-orange-800 ring-1 ring-orange-200">
            <Siren className="size-3" />
            Emergency change · admin only
          </span>
        ) : (
          <span className="badge bg-brand-50 text-brand-700">Production deployment</span>
        )
      }
      subtitle={
        slotContext ? (
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="inline-flex items-center gap-1.5">
              <Calendar className="size-4" />
              {slotContext.weekday}, {slotContext.dateLabel}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Clock className="size-4" />
              {slotContext.slotName} · {slotContext.timeLabel}
            </span>
          </span>
        ) : undefined
      }
      footer={
        created ? (
          <div className="flex justify-end">
            <button type="button" className="btn-primary" onClick={onClose}>
              Done
            </button>
          </div>
        ) : (
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button type="button" className="btn-secondary" onClick={onClose} disabled={saving}>
              Cancel
            </button>
            <button type="submit" form={formId} className="btn-primary" disabled={saving}>
              {saving ? <Spinner className="size-4" /> : null}
              {mode === 'create'
                ? isEmergency
                  ? 'Book emergency change'
                  : 'Confirm booking'
                : 'Save changes'}
            </button>
          </div>
        )
      }
    >
      {created ? (
        <div className="space-y-5">
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
            <p className="flex items-center gap-2 text-sm font-semibold text-emerald-900">
              <Check className="size-4" />
              Deployment slot booked successfully.
            </p>
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
              <dt className="text-emerald-900/70">Booking reference</dt>
              <dd className="font-semibold tnum text-emerald-950">
                {created.booking.booking_reference}
              </dd>
              <dt className="text-emerald-900/70">Date</dt>
              <dd className="text-emerald-950">
                {formatDate(created.booking.deployment_date)}
              </dd>
              <dt className="text-emerald-900/70">Slot</dt>
              <dd className="text-emerald-950">
                {created.booking.slot_label} · {created.booking.slot_time}
              </dd>
              <dt className="text-emerald-900/70">Tenant</dt>
              <dd className="text-emerald-950">{created.booking.tenant_name}</dd>
            </dl>
          </div>

          <p className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            <Alert className="mt-0.5 size-4 shrink-0" />
            <span>Your authenticated account owns this change record and controls future edits and documents.</span>
          </p>

          <div>
            <h3 className="mb-2 text-sm font-semibold text-ink">Attach deployment documents</h3>
            <DocumentUploader
              booking={created.booking}
              settings={settings}
              isAdmin={isAdmin}
              canManage={!isAdmin}
              onUpdated={(updated) => {
                setCreated({ ...created, booking: updated })
                onSaved()
              }}
            />
          </div>

          <DocumentReadinessPanel readiness={created.booking.documents} />
        </div>
      ) : (
        <BookingForm
          formId={formId}
          values={values}
          tenants={tenants}
          errors={errors}
          settings={settings}
          isEmergency={isEmergency}
          isAdmin={isAdmin}
          onChange={update}
          onSubmit={submit}
        />
      )}
    </Drawer>
  )
}
