import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../services/api'
import type {
  AdminSettings,
  Holiday,
  SlotConfig,
} from '../types'
import { formatDate, formatSlotTime } from '../utils/dates'
import { AdminTenantManager } from './AdminTenantManager'
import { AdminUserManager } from './AdminUserManager'
import { Drawer } from './Drawer'
import { DocumentSettings } from './DocumentSettings'
import { Calendar, Document, ChevronRight, History, Plus, Settings, Shield, Sparkles, Spinner, Sun, Trash, User } from './Icons'
import { CheckboxField, SelectField, TextField } from './FormControls'
import { ConfirmationModal } from './Modal'
import { useToast } from './ToastNotification'

type Tab =
  | 'users'
  | 'tenants'
  | 'general'
  | 'slots'
  | 'holidays'
  | 'documents'
  | 'notifications'

const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
  { key: 'users', label: 'Accounts', icon: <User className="size-4" /> },
  { key: 'tenants', label: 'Tenant settings', icon: <Shield className="size-4" /> },
  { key: 'general', label: 'General', icon: <Settings className="size-4" /> },
  { key: 'slots', label: 'Slots', icon: <Calendar className="size-4" /> },
  { key: 'holidays', label: 'Holidays', icon: <Sun className="size-4" /> },
  { key: 'documents', label: 'Document uploads', icon: <Document className="size-4" /> },
  { key: 'notifications', label: 'Notifications', icon: <Settings className="size-4" /> },
]

interface AdminPanelProps {
  open: boolean
  onClose: () => void
  timezone: string
  currentUserId: number
  isOwner: boolean
  onChanged: () => void
}

export function AdminPanel({ open, onClose, timezone, currentUserId, isOwner, onChanged }: AdminPanelProps) {
  const toast = useToast()
  const [tab, setTab] = useState<Tab>('users')
  const [aiEnabled, setAiEnabled] = useState<boolean | null>(null)
  const [aiBusy, setAiBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    let active = true
    api.getAIAccess()
      .then((value) => { if (active) setAiEnabled(value.ai_enabled) })
      .catch(() => { if (active) setAiEnabled(null) })
    return () => { active = false }
  }, [open])

  async function toggleMasterAI() {
    if (aiEnabled === null || aiBusy) return
    setAiBusy(true)
    try {
      const updated = await api.updateAIAccess({ ai_enabled: !aiEnabled })
      setAiEnabled(updated.ai_enabled)
      window.dispatchEvent(new Event('pds-ai-access-changed'))
      toast.success(updated.ai_enabled ? 'PDS AI enabled.' : 'PDS AI disabled.')
    } catch (caught) {
      toast.error('Could not update PDS AI', caught instanceof ApiError ? caught.message : '')
    } finally {
      setAiBusy(false)
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width="xl"
      title="Release controls"
      eyebrow={<span className="badge bg-brand-50 text-brand-700">{isOwner ? 'Owner' : 'Release Manager'}</span>}
      subtitle="Configuration applies immediately to the weekly board."
    >
      <div className="mb-3 flex flex-wrap justify-end gap-1">
        <a href="#/admin/groups" onClick={onClose} className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-ink-muted hover:bg-brand-50 hover:text-brand-700"><Shield className="size-3.5" />Groups<ChevronRight className="size-3" /></a>
        <button
          type="button"
          onClick={() => void toggleMasterAI()}
          disabled={aiEnabled === null || aiBusy}
          title={aiEnabled ? 'Disable PDS AI globally' : 'Enable PDS AI globally'}
          className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition ${aiEnabled ? 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100' : 'text-ink-muted hover:bg-brand-50 hover:text-brand-700'} disabled:opacity-50`}
        >
          {aiBusy ? <Spinner className="size-3.5" /> : <Sparkles className="size-3.5" />}
          AI Enable
          <span className={`rounded-full px-1.5 py-0.5 text-[10px] ${aiEnabled ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
            {aiEnabled === null ? '…' : aiEnabled ? 'Active' : 'Off'}
          </span>
        </button>
        <a href="#/audit" onClick={onClose} className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-ink-muted hover:bg-brand-50 hover:text-brand-700"><History className="size-3.5" />Audit<ChevronRight className="size-3" /></a>
      </div>
      <nav className="mb-4 grid grid-cols-2 gap-1 rounded-xl bg-slate-100/80 p-1.5 sm:grid-cols-3" aria-label="Release control sections">
        {TABS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            onClick={() => setTab(entry.key)}
            aria-current={tab === entry.key}
            className={`flex min-w-0 items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-xs font-semibold transition-colors sm:text-sm ${
              tab === entry.key
                ? 'bg-white text-brand-700 shadow-sm ring-1 ring-slate-200/70'
                : 'text-ink-muted hover:bg-canvas hover:text-ink'
            }`}
          >
            {entry.icon}
            {entry.label}
          </button>
        ))}
      </nav>

      {tab === 'users' ? (
        <AdminUserManager timezone={timezone} currentUserId={currentUserId} isOwner={isOwner} />
      ) : null}
      {tab === 'tenants' ? <AdminTenantManager onChanged={onChanged} /> : null}
      {tab === 'general' ? <GeneralSettings onChanged={onChanged} /> : null}
      {tab === 'slots' ? <SlotConfiguration onChanged={onChanged} /> : null}
      {tab === 'holidays' ? <HolidayManager onChanged={onChanged} /> : null}
      {tab === 'documents' ? <DocumentSettings onChanged={onChanged} /> : null}
      {tab === 'notifications' ? <TeamsNotifications isOwner={isOwner} /> : null}
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
      description="The default number of normal slots for every deployment date. The Owner and Release Managers can still add or remove slots on one date from the board."
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
              booking_freeze_dates: data.booking_freeze_dates,
              jira_required_at_booking: data.jira_required_at_booking,
              max_file_size_mb: data.max_file_size_mb,
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
            hint="Saving a higher number automatically creates the missing slot rows. New slots default to 09:00 PM–05:00 AM. Emergency changes remain separate."
          />
          <TextField
            label="Default weekly booking limit"
            name="weekly_booking_limit"
            type="number"
            min={1}
            max={25}
            value={String(data.weekly_booking_limit)}
            onChange={(v) => setData({ ...data, weekly_booking_limit: Number(v) || 1 })}
            hint="Fallback for tenants that do not have their own weekly limit."
          />
          <TextField
            label="Freeze upcoming deployment dates"
            name="booking_freeze_dates"
            type="number"
            min={0}
            max={25}
            value={String(data.booking_freeze_dates)}
            onChange={(v) => setData({ ...data, booking_freeze_dates: Math.max(0, Number(v) || 0) })}
            hint="Scheduling on past dates and today stays protected. Today and the previous seven days can be unlocked for extra uploads; admins can close active records or reopen closed schedules at any age. Upcoming valid deployment dates are locked until explicitly unlocked. Friday/Saturday and full-day holidays are skipped when counting."
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
              label="Require Jira No. during booking"
              name="jira_required_at_booking"
              checked={data.jira_required_at_booking}
              onChange={(v) => setData({ ...data, jira_required_at_booking: v })}
              hint="When off, Jira No. can be added later."
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

/* --------------------------- Notifications ------------------------------ */

function TeamsNotifications({ isOwner }: { isOwner: boolean }) {
  const toast = useToast()
  const { data, setData, error, reload } = useAsyncSection(() => api.getTeamsNotifications())
  const [webhook, setWebhook] = useState('')
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)

  async function save() {
    if (!data) return
    setSaving(true)
    try {
      const updated = await api.updateTeamsNotifications({
        enabled: data.enabled,
        ...(webhook.trim() ? { webhook_url: webhook.trim() } : {}),
      })
      setData(updated)
      setWebhook('')
      toast.success('Teams notification settings saved.')
    } catch (caught) {
      toast.error('Could not save Teams settings', caught instanceof ApiError ? caught.message : '')
    } finally {
      setSaving(false)
    }
  }

  async function clearWebhook() {
    setSaving(true)
    try {
      const updated = await api.updateTeamsNotifications({ clear_webhook: true })
      setData(updated)
      setWebhook('')
      toast.success('Teams webhook removed. Notifications are off.')
    } catch (caught) {
      toast.error('Could not remove Teams webhook', caught instanceof ApiError ? caught.message : '')
    } finally {
      setSaving(false)
    }
  }

  async function test() {
    setTesting(true)
    try {
      await api.testTeamsNotification()
      toast.success('Test notification sent to Microsoft Teams.')
    } catch (caught) {
      toast.error('Teams test failed', caught instanceof ApiError ? caught.message : '')
      reload()
    } finally {
      setTesting(false)
    }
  }

  return (
    <SectionShell
      title="Microsoft Teams notifications"
      description={isOwner ? "Send a Teams message when a PDS deployment is successfully scheduled. Configuration is stored by PDS; no Teams environment variables are required." : "Teams booking notifications are managed by the Owner. Release Managers can view the current status but cannot change the webhook or send tests."}
      error={error}
      loading={!data}
    >
      {data ? (
        <div className="space-y-4">
          <div className="rounded-lg border border-line p-4">
            <CheckboxField
              label="Enable booking notifications"
              name="teams-notifications-enabled"
              checked={data.enabled}
              disabled={!isOwner}
              onChange={(enabled) => setData({ ...data, enabled })}
              hint="A Teams outage never blocks or rolls back a successful PDS booking."
            />
          </div>
          {isOwner ? <TextField
            label={data.webhook_configured ? 'Replace Teams webhook URL' : 'Teams webhook URL'}
            name="teams-webhook-url"
            type="password"
            value={webhook}
            onChange={setWebhook}
            placeholder={data.webhook_configured ? 'Webhook already configured — enter a new URL only to replace it' : 'https://...'}
            hint={data.webhook_configured ? 'Configured. For security, PDS never sends the saved webhook URL back to the browser.' : 'Paste the Microsoft Teams Workflows webhook URL. Only Microsoft Power Platform webhook hosts are accepted.'}
          /> : null}
          {isOwner ? <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-primary" disabled={saving} onClick={() => void save()}>
              {saving ? <Spinner className="size-4" /> : null} Save Teams settings
            </button>
            <button type="button" className="btn-secondary" disabled={testing || !data.webhook_configured} onClick={() => void test()}>
              {testing ? <Spinner className="size-4" /> : null} Send test notification
            </button>
            {data.webhook_configured ? (
              <button type="button" className="btn-secondary" disabled={saving} onClick={() => void clearWebhook()}>
                Remove webhook
              </button>
            ) : null}
          </div> : null}
          {data.webhook_configured && data.webhook_valid === false ? (
            <p role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
              The saved webhook is not a Teams Workflows URL (for example an old Office 365 connector), so no
              notifications are being sent. {isOwner ? 'Paste the Workflows webhook URL above to replace it.' : 'Ask the Owner to replace it.'}
            </p>
          ) : null}
          <p className="text-xs text-ink-muted">
            Status: {!data.webhook_configured ? 'Webhook not configured' : data.webhook_valid === false ? 'Webhook needs replacing' : 'Webhook configured'} · {data.enabled ? 'Notifications enabled' : 'Notifications disabled'}
          </p>
        </div>
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
                    start_time: '21:00:00',
                    end_time: '05:00:00',
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
      description="A full-day holiday closes every normal slot. Emergency CRQs remain a separate Owner/Release Manager-only queue subject to date protection."
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
