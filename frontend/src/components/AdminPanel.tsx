import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../services/api'
import type {
  AdminSettings,
  BookingSummary,
  DailyOverride,
  DocumentCategory,
  Holiday,
  SlotConfig,
} from '../types'
import { formatDate, formatSlotTime } from '../utils/dates'
import { AdminTenantManager } from './AdminTenantManager'
import { AdminUserManager } from './AdminUserManager'
import { AuditHistory } from './AuditHistory'
import { Drawer } from './Drawer'
import { Alert, Calendar, Check, History, Plus, Settings, Shield, Siren, Spinner, Sun, Trash, User } from './Icons'
import { CheckboxField, SelectField, TextField } from './FormControls'
import { ConfirmationModal } from './Modal'
import { BookingStatusBadge, LockBadge } from './StatusBadge'
import { useToast } from './ToastNotification'

type Tab =
  | 'users'
  | 'tenants'
  | 'general'
  | 'slots'
  | 'holidays'
  | 'overrides'
  | 'documents'
  | 'bookings'
  | 'audit'

const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
  { key: 'users', label: 'Users', icon: <User className="size-4" /> },
  { key: 'tenants', label: 'Tenants', icon: <Shield className="size-4" /> },
  { key: 'general', label: 'General', icon: <Settings className="size-4" /> },
  { key: 'slots', label: 'Slots', icon: <Calendar className="size-4" /> },
  { key: 'holidays', label: 'Holidays', icon: <Sun className="size-4" /> },
  { key: 'overrides', label: 'Daily override', icon: <Siren className="size-4" /> },
  { key: 'documents', label: 'Documents', icon: <Check className="size-4" /> },
  { key: 'bookings', label: 'Bookings', icon: <Alert className="size-4" /> },
  { key: 'audit', label: 'Audit', icon: <History className="size-4" /> },
]

const DOCUMENT_LABELS: Record<DocumentCategory, string> = {
  TEST_RESULTS: 'Non-Production Test Result',
  INVENTORY: 'Inventory File',
  IMPLEMENTATION_PLAN: 'Implementation Document',
  VALIDATION_PLAN: 'Validation Plan',
  DBA_SCRIPT: 'DBA Script',
  SUPPORTING_DOCUMENTS: 'Supporting Documents',
}

interface AdminPanelProps {
  open: boolean
  onClose: () => void
  timezone: string
  onChanged: () => void
  onOpenBooking: (bookingId: number) => void
}

export function AdminPanel({ open, onClose, timezone, onChanged, onOpenBooking }: AdminPanelProps) {
  const [tab, setTab] = useState<Tab>('users')

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width="xl"
      title="Admin controls"
      eyebrow={<span className="badge bg-brand-50 text-brand-700">Administrator</span>}
      subtitle="Configuration applies immediately to the weekly board."
    >
      <nav className="-mx-1 mb-5 flex gap-1 overflow-x-auto px-1 pb-1" aria-label="Admin sections">
        {TABS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            onClick={() => setTab(entry.key)}
            aria-current={tab === entry.key}
            className={`flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-semibold transition-colors ${
              tab === entry.key
                ? 'bg-brand-600 text-white'
                : 'text-ink-muted hover:bg-canvas hover:text-ink'
            }`}
          >
            {entry.icon}
            {entry.label}
          </button>
        ))}
      </nav>

      {tab === 'users' ? <AdminUserManager timezone={timezone} /> : null}
      {tab === 'tenants' ? <AdminTenantManager onChanged={onChanged} /> : null}
      {tab === 'general' ? <GeneralSettings onChanged={onChanged} /> : null}
      {tab === 'slots' ? <SlotConfiguration onChanged={onChanged} /> : null}
      {tab === 'holidays' ? <HolidayManager onChanged={onChanged} /> : null}
      {tab === 'overrides' ? <DailyOverrideManager onChanged={onChanged} /> : null}
      {tab === 'documents' ? <DocumentSettings onChanged={onChanged} /> : null}
      {tab === 'bookings' ? (
        <BookingManagement
          timezone={timezone}
          onChanged={onChanged}
          onOpenBooking={onOpenBooking}
        />
      ) : null}
      {tab === 'audit' ? <AuditHistory timezone={timezone} /> : null}
    </Drawer>
  )
}

/* -------------------------------------------------------------------------- */

function useAsyncSection<T>(loader: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(() => {
    setError(null)
    loader()
      .then(setData)
      .catch((caught) => setError(caught instanceof ApiError ? caught.message : 'Request failed.'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(reload, [reload])

  return { data, setData, error, reload }
}

function SectionShell({
  title,
  description,
  children,
  error,
  loading,
}: {
  title: string
  description?: string
  children: React.ReactNode
  error?: string | null
  loading?: boolean
}) {
  return (
    <section>
      <h3 className="text-sm font-semibold text-ink">{title}</h3>
      {description ? <p className="mt-0.5 text-xs text-ink-muted">{description}</p> : null}
      {error ? <p className="mt-3 text-sm text-rose-600">{error}</p> : null}
      {loading ? (
        <div className="flex items-center gap-2 py-8 text-sm text-ink-muted">
          <Spinner className="size-4" />
          Loading…
        </div>
      ) : (
        <div className="mt-4">{children}</div>
      )}
    </section>
  )
}

/* ------------------------------ General ---------------------------------- */

function GeneralSettings({ onChanged }: { onChanged: () => void }) {
  const toast = useToast()
  const { data, setData, error } = useAsyncSection(() => api.getSettings())
  const [saving, setSaving] = useState(false)

  async function save(patch: Partial<AdminSettings>) {
    setSaving(true)
    try {
      const updated = await api.updateSettings(patch)
      setData(updated)
      onChanged()
      toast.success('Settings updated.')
    } catch (caught) {
      toast.error('Could not save settings', caught instanceof ApiError ? caught.message : '')
    } finally {
      setSaving(false)
    }
  }

  return (
    <SectionShell
      title="General settings"
      description="Applies to every day unless a daily override says otherwise."
      error={error}
      loading={!data}
    >
      {data ? (
        <form
          className="grid gap-4 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault()
            void save({
              regular_slots_per_day: data.regular_slots_per_day,
              weekly_booking_limit: data.weekly_booking_limit,
              max_file_size_mb: data.max_file_size_mb,
              emergency_changes_enabled: data.emergency_changes_enabled,
            })
          }}
        >
          <TextField
            label="Default regular slots per day"
            name="regular_slots_per_day"
            type="number"
            min={1}
            max={12}
            value={String(data.regular_slots_per_day)}
            onChange={(v) => setData({ ...data, regular_slots_per_day: Number(v) || 1 })}
            hint="Emergency changes are a separate admin-only queue and never use a slot."
          />
          <TextField
            label="Weekly booking limit per tenant"
            name="weekly_booking_limit"
            type="number"
            min={1}
            max={25}
            value={String(data.weekly_booking_limit)}
            onChange={(v) => setData({ ...data, weekly_booking_limit: Number(v) || 1 })}
            hint="Regular deployments only; emergency changes never count."
          />
          <TextField
            label="Maximum file size (MB)"
            name="max_file_size_mb"
            type="number"
            min={1}
            max={200}
            value={String(data.max_file_size_mb)}
            onChange={(v) => setData({ ...data, max_file_size_mb: Number(v) || 1 })}
          />
          <div className="space-y-3 sm:col-span-2">
            <CheckboxField
              label="Emergency changes enabled"
              name="emergency_changes_enabled"
              checked={data.emergency_changes_enabled}
              onChange={(v) => setData({ ...data, emergency_changes_enabled: v })}
              hint="When off, no emergency change can be queued on any date."
            />
          </div>
          <div className="sm:col-span-2">
            <button type="submit" className="btn-primary" disabled={saving}>
              {saving ? <Spinner className="size-4" /> : null}
              Save settings
            </button>
          </div>
        </form>
      ) : null}
    </SectionShell>
  )
}

/* -------------------------------- Slots ---------------------------------- */

function SlotConfiguration({ onChanged }: { onChanged: () => void }) {
  const toast = useToast()
  const { data, setData, error, reload } = useAsyncSection(() => api.getSlots())
  const [saving, setSaving] = useState(false)

  function patch(index: number, change: Partial<SlotConfig>) {
    if (!data) return
    setData(data.map((slot, i) => (i === index ? { ...slot, ...change } : slot)))
  }

  async function save() {
    if (!data) return
    setSaving(true)
    try {
      const saved = await api.replaceSlots(
        data.map(({ slot_number, name, start_time, end_time, enabled }) => ({
          slot_number,
          name,
          start_time,
          end_time,
          enabled,
        })),
      )
      setData(saved)
      onChanged()
      toast.success('Slot configuration saved.')
    } catch (caught) {
      toast.error('Could not save slots', caught instanceof ApiError ? caught.message : '')
      reload()
    } finally {
      setSaving(false)
    }
  }

  return (
    <SectionShell
      title="Slot configuration"
      description="Name and times for each normal deployment slot. Slots holding upcoming changes cannot be removed."
      error={error}
      loading={!data}
    >
      {data ? (
        <div className="space-y-3">
          {data.map((slot, index) => (
            <div key={slot.slot_number} className="rounded-lg border border-line p-3">
              <div className="grid gap-3 sm:grid-cols-4">
                <TextField
                  label={`Slot ${slot.slot_number} name`}
                  name={`slot-name-${slot.slot_number}`}
                  value={slot.name}
                  onChange={(v) => patch(index, { name: v })}
                />
                <TextField
                  label="Start"
                  name={`slot-start-${slot.slot_number}`}
                  type="time"
                  value={slot.start_time.slice(0, 5)}
                  onChange={(v) => patch(index, { start_time: `${v}:00` })}
                />
                <TextField
                  label="End"
                  name={`slot-end-${slot.slot_number}`}
                  type="time"
                  value={slot.end_time.slice(0, 5)}
                  onChange={(v) => patch(index, { end_time: `${v}:00` })}
                />
                <div className="flex flex-col justify-end gap-2 pb-1">
                  <CheckboxField
                    label="Enabled"
                    name={`slot-enabled-${slot.slot_number}`}
                    checked={slot.enabled}
                    onChange={(v) => patch(index, { enabled: v })}
                  />
                </div>
              </div>
              <p className="mt-2 text-xs text-ink-muted">
                Board label: {formatSlotTime(slot.start_time)} – {formatSlotTime(slot.end_time)}
              </p>
            </div>
          ))}

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-secondary"
              onClick={() =>
                setData([
                  ...data,
                  {
                    slot_number: Math.max(...data.map((s) => s.slot_number)) + 1,
                    name: `Slot ${Math.max(...data.map((s) => s.slot_number)) + 1}`,
                    start_time: '18:00:00',
                    end_time: '20:00:00',
                    enabled: true,
                  },
                ])
              }
            >
              <Plus className="size-4" />
              Add slot
            </button>
            {data.length > 1 ? (
              <button
                type="button"
                className="btn-ghost text-rose-600"
                onClick={() => setData(data.slice(0, -1))}
              >
                <Trash className="size-4" />
                Remove last slot
              </button>
            ) : null}
            <button type="button" className="btn-primary ml-auto" onClick={() => void save()} disabled={saving}>
              {saving ? <Spinner className="size-4" /> : null}
              Save slot configuration
            </button>
          </div>
        </div>
      ) : null}
    </SectionShell>
  )
}

/* ------------------------------ Holidays --------------------------------- */

const EMPTY_HOLIDAY: Omit<Holiday, 'id'> = {
  holiday_date: '',
  name: '',
  description: '',
  is_full_day: true,
  allow_emergency: true,
}

function HolidayManager({ onChanged }: { onChanged: () => void }) {
  const toast = useToast()
  const { data, error, reload } = useAsyncSection(() => api.getHolidays())
  const [draft, setDraft] = useState<Omit<Holiday, 'id'>>(EMPTY_HOLIDAY)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [pendingDelete, setPendingDelete] = useState<Holiday | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit() {
    if (!draft.holiday_date || !draft.name.trim()) {
      toast.error('A holiday needs a date and a name.')
      return
    }
    setBusy(true)
    try {
      if (editingId) await api.updateHoliday(editingId, draft)
      else await api.createHoliday(draft)
      setDraft(EMPTY_HOLIDAY)
      setEditingId(null)
      reload()
      onChanged()
      toast.success(editingId ? 'Holiday updated.' : 'Holiday added.')
    } catch (caught) {
      toast.error('Could not save the holiday', caught instanceof ApiError ? caught.message : '')
    } finally {
      setBusy(false)
    }
  }

  async function remove(holiday: Holiday) {
    setBusy(true)
    try {
      await api.deleteHoliday(holiday.id)
      setPendingDelete(null)
      reload()
      onChanged()
      toast.success('Holiday deleted.')
    } catch (caught) {
      toast.error('Could not delete the holiday', caught instanceof ApiError ? caught.message : '')
    } finally {
      setBusy(false)
    }
  }

  return (
    <SectionShell
      title="Holiday management"
      description="A full-day holiday closes every normal slot. The emergency queue can stay open to administrators."
      error={error}
      loading={!data}
    >
      <form
        className="mb-5 grid gap-4 rounded-lg border border-line bg-canvas/50 p-4 sm:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
      >
        <TextField
          label="Date"
          name="holiday_date"
          type="date"
          required
          value={draft.holiday_date}
          onChange={(v) => setDraft({ ...draft, holiday_date: v })}
        />
        <TextField
          label="Holiday name"
          name="holiday_name"
          required
          value={draft.name}
          onChange={(v) => setDraft({ ...draft, name: v })}
          placeholder="Indian Public Holiday"
        />
        <TextField
          label="Description"
          name="holiday_description"
          value={draft.description ?? ''}
          onChange={(v) => setDraft({ ...draft, description: v })}
          hint="Optional."
          className="sm:col-span-2"
        />
        <SelectField
          label="Duration"
          name="holiday_full_day"
          value={draft.is_full_day ? 'full' : 'partial'}
          onChange={(v) => setDraft({ ...draft, is_full_day: v === 'full' })}
          options={[
            { value: 'full', label: 'Full day — all regular slots closed' },
            { value: 'partial', label: 'Partial day — regular slots stay open' },
          ]}
        />
        <SelectField
          label="Allow emergency deployment"
          name="holiday_allow_emergency"
          value={draft.allow_emergency ? 'yes' : 'no'}
          onChange={(v) => setDraft({ ...draft, allow_emergency: v === 'yes' })}
          options={[
            { value: 'yes', label: 'Yes' },
            { value: 'no', label: 'No' },
          ]}
        />
        <div className="flex gap-2 sm:col-span-2">
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? <Spinner className="size-4" /> : <Plus className="size-4" />}
            {editingId ? 'Update holiday' : 'Add holiday'}
          </button>
          {editingId ? (
            <button
              type="button"
              className="btn-secondary"
              onClick={() => {
                setEditingId(null)
                setDraft(EMPTY_HOLIDAY)
              }}
            >
              Cancel edit
            </button>
          ) : null}
        </div>
      </form>

      {data && data.length === 0 ? (
        <p className="text-sm text-ink-muted">No holidays defined yet.</p>
      ) : (
        <ul className="space-y-2">
          {data?.map((holiday) => (
            <li
              key={holiday.id}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-line p-3"
            >
              <Sun className="size-4 shrink-0 text-amber-600" />
              <span className="text-sm font-semibold tnum text-ink">
                {formatDate(holiday.holiday_date)}
              </span>
              <span className="text-sm text-ink">{holiday.name}</span>
              <span className="badge bg-canvas text-ink-muted ring-1 ring-line">
                {holiday.is_full_day ? 'Full day' : 'Partial'}
              </span>
              <span className="badge bg-canvas text-ink-muted ring-1 ring-line">
                Emergency {holiday.allow_emergency ? 'allowed' : 'closed'}
              </span>
              <span className="ml-auto flex gap-1.5">
                <button
                  type="button"
                  className="btn-secondary btn-sm"
                  onClick={() => {
                    setEditingId(holiday.id)
                    setDraft({
                      holiday_date: holiday.holiday_date,
                      name: holiday.name,
                      description: holiday.description ?? '',
                      is_full_day: holiday.is_full_day,
                      allow_emergency: holiday.allow_emergency,
                    })
                  }}
                >
                  Edit
                </button>
                <button
                  type="button"
                  className="btn-ghost btn-sm text-rose-600"
                  onClick={() => setPendingDelete(holiday)}
                >
                  <Trash className="size-3.5" />
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <ConfirmationModal
        open={pendingDelete !== null}
        onClose={() => setPendingDelete(null)}
        onConfirm={() => pendingDelete && void remove(pendingDelete)}
        title="Delete holiday?"
        facts={
          pendingDelete
            ? [
                { label: 'Date', value: formatDate(pendingDelete.holiday_date) },
                { label: 'Name', value: pendingDelete.name },
              ]
            : []
        }
        note="Regular slots on this date will become bookable again."
        confirmLabel="Delete holiday"
        cancelLabel="Keep holiday"
        busy={busy}
      />
    </SectionShell>
  )
}

/* --------------------------- Daily overrides ----------------------------- */

function DailyOverrideManager({ onChanged }: { onChanged: () => void }) {
  const toast = useToast()
  const { data, error, reload } = useAsyncSection(() => api.getOverrides())
  const [date, setDate] = useState('')
  const [regularSlots, setRegularSlots] = useState('')
  const [emergency, setEmergency] = useState<'inherit' | 'yes' | 'no'>('inherit')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit() {
    if (!date) {
      toast.error('Choose the date to override.')
      return
    }
    setBusy(true)
    try {
      await api.upsertOverride({
        override_date: date,
        regular_slots: regularSlots === '' ? null : Number(regularSlots),
        emergency_enabled: emergency === 'inherit' ? null : emergency === 'yes',
        note: note.trim() || null,
      })
      setDate('')
      setRegularSlots('')
      setEmergency('inherit')
      setNote('')
      reload()
      onChanged()
      toast.success('Daily override saved.')
    } catch (caught) {
      toast.error('Could not save the override', caught instanceof ApiError ? caught.message : '')
    } finally {
      setBusy(false)
    }
  }

  async function clear(override: DailyOverride) {
    setBusy(true)
    try {
      await api.deleteOverride(override.id)
      reload()
      onChanged()
      toast.success('Override cleared.')
    } catch (caught) {
      toast.error('Could not clear the override', caught instanceof ApiError ? caught.message : '')
    } finally {
      setBusy(false)
    }
  }

  return (
    <SectionShell
      title="Daily slot override"
      description="Configure one date differently from the default grid — for example a special-date slot configuration."
      error={error}
      loading={!data}
    >
      <form
        className="mb-5 grid gap-4 rounded-lg border border-line bg-canvas/50 p-4 sm:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
      >
        <TextField label="Date" name="override_date" type="date" required value={date} onChange={setDate} />
        <TextField
          label="Regular slots on this date"
          name="override_slots"
          type="number"
          min={0}
          max={12}
          value={regularSlots}
          onChange={setRegularSlots}
          hint="Leave blank to inherit the default."
        />
        <SelectField
          label="Emergency changes"
          name="override_emergency"
          value={emergency}
          onChange={(v) => setEmergency(v as 'inherit' | 'yes' | 'no')}
          options={[
            { value: 'inherit', label: 'Inherit the default' },
            { value: 'yes', label: 'Enabled' },
            { value: 'no', label: 'Disabled' },
          ]}
        />
        <TextField label="Note" name="override_note" value={note} onChange={setNote} hint="Optional." />
        <div className="sm:col-span-2">
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? <Spinner className="size-4" /> : <Plus className="size-4" />}
            Save override
          </button>
        </div>
      </form>

      {data && data.length === 0 ? (
        <p className="text-sm text-ink-muted">No daily overrides configured.</p>
      ) : (
        <ul className="space-y-2">
          {data?.map((override) => (
            <li
              key={override.id}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-line p-3 text-sm"
            >
              <span className="font-semibold tnum text-ink">{formatDate(override.override_date)}</span>
              <span className="text-ink-muted">
                Regular slots:{' '}
                <span className="font-medium text-ink">
                  {override.regular_slots ?? 'default'}
                </span>
              </span>
              <span className="text-ink-muted">
                Emergency:{' '}
                <span className="font-medium text-ink">
                  {override.emergency_enabled === null
                    ? 'default'
                    : override.emergency_enabled
                      ? 'enabled'
                      : 'disabled'}
                </span>
              </span>
              {override.note ? <span className="text-xs text-ink-muted">{override.note}</span> : null}
              <button
                type="button"
                className="btn-ghost btn-sm ml-auto text-rose-600"
                onClick={() => void clear(override)}
                disabled={busy}
              >
                <Trash className="size-3.5" />
                Clear
              </button>
            </li>
          ))}
        </ul>
      )}
    </SectionShell>
  )
}

/* --------------------------- Document settings --------------------------- */

function DocumentSettings({ onChanged }: { onChanged: () => void }) {
  const toast = useToast()
  const { data, setData, error } = useAsyncSection(() => api.getSettings())
  const [busy, setBusy] = useState(false)

  async function save(mandatory: DocumentCategory[]) {
    setBusy(true)
    try {
      const updated = await api.updateSettings({ mandatory_documents: mandatory })
      setData(updated)
      onChanged()
      toast.success('Document requirements updated.')
    } catch (caught) {
      toast.error('Could not save', caught instanceof ApiError ? caught.message : '')
    } finally {
      setBusy(false)
    }
  }

  return (
    <SectionShell
      title="Document settings"
      description="Choose which document categories are mandatory. Readiness on the board is calculated from this list."
      error={error}
      loading={!data}
    >
      {data ? (
        <div className="space-y-3">
          {(Object.keys(DOCUMENT_LABELS) as DocumentCategory[]).map((category) => (
            <CheckboxField
              key={category}
              label={DOCUMENT_LABELS[category]}
              name={`mandatory-${category}`}
              checked={data.mandatory_documents.includes(category)}
              onChange={(checked) => {
                const next = checked
                  ? [...data.mandatory_documents, category]
                  : data.mandatory_documents.filter((c) => c !== category)
                setData({ ...data, mandatory_documents: next })
              }}
              hint={
                category === 'SUPPORTING_DOCUMENTS'
                  ? 'Accepts multiple files.'
                  : undefined
              }
            />
          ))}
          <button
            type="button"
            className="btn-primary"
            disabled={busy}
            onClick={() => void save(data.mandatory_documents)}
          >
            {busy ? <Spinner className="size-4" /> : null}
            Save document requirements
          </button>
        </div>
      ) : null}
    </SectionShell>
  )
}

/* --------------------------- Booking management --------------------------- */

function BookingManagement({
  timezone,
  onChanged,
  onOpenBooking,
}: {
  timezone: string
  onChanged: () => void
  onOpenBooking: (bookingId: number) => void
}) {
  const toast = useToast()
  const [bookings, setBookings] = useState<BookingSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pendingDelete, setPendingDelete] = useState<BookingSummary | null>(null)
  const [busy, setBusy] = useState(false)

  const loadBookings = useCallback(() => {
    setError(null)
    api
      .listBookings(true)
      .then(setBookings)
      .catch((caught) => {
        setBookings([])
        setError(caught instanceof ApiError ? caught.message : 'Could not load bookings.')
      })
  }, [])

  useEffect(loadBookings, [loadBookings])

  async function hardDelete(booking: BookingSummary) {
    setBusy(true)
    try {
      await api.deleteBooking(booking.id)
      setPendingDelete(null)
      loadBookings()
      onChanged()
      toast.success('Booking deleted.', `${booking.booking_reference} and its documents were removed.`)
    } catch (caught) {
      toast.error('Could not delete the booking', caught instanceof ApiError ? caught.message : '')
    } finally {
      setBusy(false)
    }
  }

  async function complete(booking: BookingSummary) {
    try {
      await api.setBookingStatus(booking.id, 'COMPLETED')
      loadBookings()
      onChanged()
      toast.success('Booking marked as completed.')
    } catch (caught) {
      toast.error('Could not update the status', caught instanceof ApiError ? caught.message : '')
    }
  }

  return (
    <SectionShell
      title="Booking management"
      description="Current and future bookings can be managed here. Past deployment records are retained as read-only history and cannot be modified or deleted."
      error={error}
      loading={!bookings}
    >
      {bookings && bookings.length === 0 ? (
        <p className="text-sm text-ink-muted">No bookings recorded yet.</p>
      ) : (
        <>
          <button type="button" className="btn-secondary btn-sm mb-3" onClick={loadBookings}>
            Refresh
          </button>
          <ul className="space-y-2">
            {bookings?.map((booking) => (
              <li key={booking.id} className="rounded-lg border border-line p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-ink">{booking.tenant_name}</span>
                  <span className="text-xs tnum text-ink-muted">{booking.booking_reference}</span>
                  <BookingStatusBadge status={booking.status} />
                  {booking.is_locked && booking.status !== 'CANCELLED' ? <LockBadge /> : null}
                  {booking.is_emergency ? (
                    <span className="badge bg-orange-100 text-orange-800">Emergency</span>
                  ) : null}
                  {!booking.documents.complete ? (
                    <span className="badge bg-amber-50 text-amber-800 ring-1 ring-amber-200">
                      Docs {booking.documents.provided_required}/{booking.documents.total_required}
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-ink-muted">
                  <span className="tnum">{formatDate(booking.deployment_date)}</span>
                  <span>Slot {booking.slot_number}</span>
                  <span>{booking.jira_number}</span>
                  <span>{booking.technology}</span>
                  <span>Verifier: {booking.verifier_name}</span>
                </p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <button
                    type="button"
                    className="btn-secondary btn-sm"
                    onClick={() => onOpenBooking(booking.id)}
                  >
                    Open
                  </button>
                  {!booking.is_past && booking.status === 'BOOKED' ? (
                    <button
                      type="button"
                      className="btn-ghost btn-sm"
                      onClick={() => void complete(booking)}
                    >
                      <Check className="size-3.5" />
                      Mark completed
                    </button>
                  ) : null}
                  {!booking.is_past ? (
                    <button
                      type="button"
                      className="btn-ghost btn-sm text-rose-600"
                      onClick={() => setPendingDelete(booking)}
                    >
                      <Trash className="size-3.5" />
                      Delete permanently
                    </button>
                  ) : (
                    <span className="badge bg-slate-100 text-slate-600 ring-1 ring-slate-200">
                      Historical · read-only
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      <div className="mt-6 border-t border-line pt-4">
        <h4 className="mb-3 text-sm font-semibold text-ink">Recent activity</h4>
        <AuditHistory timezone={timezone} />
      </div>

      <ConfirmationModal
        open={pendingDelete !== null}
        onClose={() => setPendingDelete(null)}
        onConfirm={() => pendingDelete && void hardDelete(pendingDelete)}
        title="Delete this booking permanently?"
        facts={
          pendingDelete
            ? [
                { label: 'Reference', value: pendingDelete.booking_reference },
                { label: 'Tenant', value: pendingDelete.tenant_name },
                { label: 'Date', value: formatDate(pendingDelete.deployment_date) },
              ]
            : []
        }
        note="The booking and every uploaded document will be removed. Its audit history and deletion event will be retained permanently."
        confirmLabel="Delete permanently"
        cancelLabel="Keep record"
        busy={busy}
      />
    </SectionShell>
  )
}
