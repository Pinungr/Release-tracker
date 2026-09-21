import { useCallback, useMemo, useState } from 'react'
import { AdminPanel } from './components/AdminPanel'
import { AppHeader } from './components/AppHeader'
import { BookingDetailsDrawer } from './components/BookingDetailsDrawer'
import { BookingDrawer, type CreateTarget } from './components/BookingDrawer'
import { Alert, Spinner } from './components/Icons'
import { ProfileModal } from './components/ProfileModal'
import { RequiredPasswordChangeScreen } from './components/RequiredPasswordChangeScreen'
import { ScheduleFilters } from './components/ScheduleFilters'
import { ScheduleSummary } from './components/ScheduleSummary'
import { SignInScreen } from './components/SignInScreen'
import { useToast } from './components/ToastNotification'
import { WeekNavigator } from './components/WeekNavigator'
import { matchesFilter, matchesSearch, WeeklySchedule } from './components/WeeklySchedule'
import { useAuthSession } from './hooks/useAuthSession'
import { useSchedule } from './hooks/useSchedule'
import { api, ApiError } from './services/api'
import type { BookingDetail, DayView, FilterKey, PublicSettings, SlotView } from './types'
import { addDays, toIsoDate, weekStart } from './utils/dates'

/** Used only until the first schedule response arrives. */
const FALLBACK_SETTINGS: PublicSettings = {
  weekly_booking_limit: 2,
  booking_freeze_dates: 2,
  jira_required_at_booking: false,
  max_file_size_mb: 20,
  mandatory_documents: [],
  document_catalog: [],
  technologies: ['Databricks', 'AzDF', 'Database', 'Application', 'Infrastructure', 'Other'],
}

export default function App() {
  const auth = useAuthSession()

  if (auth.checking) {
    return (
      <div className="grid min-h-dvh place-items-center text-sm text-ink-muted">
        <span className="inline-flex items-center gap-3">
          <Spinner className="size-5" />
          Restoring your session…
        </span>
      </div>
    )
  }

  if (!auth.isAuthenticated) {
    return <SignInScreen onSignedIn={auth.signIn} />
  }

  if (auth.user?.must_change_password) {
    return (
      <RequiredPasswordChangeScreen
        user={auth.user}
        onChanged={auth.refreshUser}
        onLogout={() => void auth.signOut()}
      />
    )
  }

  // Remounting on identity change clears every cached booking and filter from
  // the previous session.
  return <Scheduler key={auth.user!.id} auth={auth} />
}

function Scheduler({ auth }: { auth: ReturnType<typeof useAuthSession> }) {
  const toast = useToast()
  const user = auth.user!

  const [anchor, setAnchor] = useState(() => weekStart(toIsoDate(new Date())))
  const { schedule, loading, error, refresh } = useSchedule(anchor)
  const settings = schedule?.settings ?? FALLBACK_SETTINGS
  const timezone = schedule?.timezone ?? 'Asia/Kolkata'

  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<FilterKey>('ALL')

  const [createTarget, setCreateTarget] = useState<CreateTarget | null>(null)
  const [editBooking, setEditBooking] = useState<BookingDetail | null>(null)
  const [bookingDrawerOpen, setBookingDrawerOpen] = useState(false)

  const [detailBooking, setDetailBooking] = useState<BookingDetail | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)

  const [profileOpen, setProfileOpen] = useState(false)
  const [adminPanelOpen, setAdminPanelOpen] = useState(false)

  /**
   * "My changes" comes straight from created_by_user_id on the board — the
   * server already tells us who owns each row, so nothing extra is fetched.
   */
  const myBookingIds = useMemo(() => {
    const mine = new Set<number>()
    if (!schedule) return mine
    for (const day of schedule.days) {
      for (const slot of day.slots) {
        if (slot.booking && (slot.booking.created_by_user_id === user.id || slot.booking.assigned_users.some((assigned) => assigned.user_id === user.id))) mine.add(slot.booking.id)
      }
      for (const booking of day.emergency_bookings) {
        if (booking.created_by_user_id === user.id || booking.assigned_users.some((assigned) => assigned.user_id === user.id)) mine.add(booking.id)
      }
    }
    return mine
  }, [schedule, user.id])

  const openBooking = useCallback(
    async (id: number) => {
      setDetailOpen(true)
      setDetailLoading(true)
      try {
        setDetailBooking(await api.getBooking(id))
      } catch (caught) {
        const message = caught instanceof ApiError ? caught.message : ''
        toast.error('Could not open the change record', message)
        setDetailOpen(false)
      } finally {
        setDetailLoading(false)
      }
    },
    [toast],
  )

  /** After any mutation, refresh both the board and the open detail drawer. */
  const refreshAll = useCallback(() => {
    refresh()
    if (detailBooking) {
      void api
        .getBooking(detailBooking.id)
        .then(setDetailBooking)
        .catch(() => undefined)
    }
  }, [refresh, detailBooking])

  function startBooking(day: DayView, slot: SlotView) {
    if (!schedule || day.is_past || day.day <= schedule.today) {
      toast.locked('Date is read-only', 'Past and current deployment dates cannot be booked or modified by any user, including administrators.')
      return
    }
    setEditBooking(null)
    setCreateTarget({ day, slot, isEmergency: false })
    setBookingDrawerOpen(true)
  }

  async function toggleSlotFreeze(day: DayView, slot: SlotView) {
    if (!auth.isAdmin || !schedule || day.is_past || day.day <= schedule.today) return
    try {
      if (slot.manually_frozen) {
        await api.unfreezeSlot(day.day, slot.slot_number)
        toast.success(`Slot ${slot.slot_number} unfrozen`, 'Normal users can book or edit this slot again.')
      } else {
        await api.freezeSlot(day.day, slot.slot_number)
        toast.locked(`Slot ${slot.slot_number} frozen`, 'Normal users can no longer book or edit this slot. Admin access remains available.')
      }
      refreshAll()
    } catch (caught) {
      toast.error(
        slot.manually_frozen ? 'Could not unfreeze the slot' : 'Could not freeze the slot',
        caught instanceof ApiError ? caught.message : '',
      )
    }
  }

  function startEmergencyBooking(day: DayView) {
    if (!schedule || day.is_past || day.day <= schedule.today) {
      toast.locked('Date is read-only', 'Past and current deployment dates cannot accept emergency changes, including for administrators.')
      return
    }
    if (!auth.isAdmin) {
      toast.locked(
        'Emergency changes are administrator only',
        'Contact an administrator to raise an emergency change.',
      )
      return
    }
    setEditBooking(null)
    setCreateTarget({ day, slot: null, isEmergency: true })
    setBookingDrawerOpen(true)
  }

  function startEdit(booking: BookingDetail) {
    if (!booking.can_edit) {
      toast.locked(
        'This booking is locked',
        booking.is_past
          ? 'Past deployment records cannot be edited by any user, including administrators.'
          : 'This booking is inside a protected date or slot freeze window.',
      )
      return
    }
    if (!auth.isAdmin && booking.created_by_user_id !== user.id) {
      toast.error('You are not authorized to edit this change record.')
      return
    }
    setCreateTarget(null)
    setEditBooking(booking)
    setBookingDrawerOpen(true)
  }

  const visibleCount = useMemo(() => {
    if (!schedule || (!query.trim() && filter === 'ALL')) return null
    return schedule.days.reduce(
      (total, day) =>
        total +
        day.slots.filter(
          (slot) => matchesSearch(slot, query) && matchesFilter(slot, filter, myBookingIds),
        ).length,
      0,
    )
  }, [schedule, query, filter, myBookingIds])

  return (
    <div className="min-h-dvh">
      <AppHeader
        timezone={timezone}
        username={user.username}
        isAdmin={auth.isAdmin}
        onProfile={() => setProfileOpen(true)}
        onAdminPanel={() => setAdminPanelOpen(true)}
        onLogout={() => void auth.signOut()}
        weekNavigator={
          <WeekNavigator
            label={schedule?.week_label ?? '—'}
            loading={loading}
            isCurrentWeek={anchor === weekStart(toIsoDate(new Date()))}
            onPrevious={() => setAnchor((current) => addDays(current, -7))}
            onNext={() => setAnchor((current) => addDays(current, 7))}
            onToday={() => setAnchor(weekStart(toIsoDate(new Date())))}
          />
        }
      />

      <main className="mx-auto max-w-[88rem] space-y-4 px-4 py-5 sm:px-6 lg:px-8">
        {error ? (
          <div className="card flex flex-wrap items-center gap-3 border-rose-200 bg-rose-50 p-4">
            <Alert className="size-5 text-rose-600" />
            <p className="text-sm text-rose-900">{error}</p>
            <button type="button" className="btn-secondary btn-sm ml-auto" onClick={refresh}>
              Retry
            </button>
          </div>
        ) : null}

        {schedule ? (
          <ScheduleSummary
            summary={schedule.summary}
            myBookingCount={myBookingIds.size}
            onShowMine={() => setFilter(filter === 'MINE' ? 'ALL' : 'MINE')}
          />
        ) : null}

        <ScheduleFilters
          query={query}
          onQueryChange={setQuery}
          filter={filter}
          onFilterChange={setFilter}
          technologies={settings.technologies}
          isAdmin={auth.isAdmin}
          resultCount={visibleCount}
        />

        <WeeklySchedule
          schedule={schedule}
          loading={loading}
          isAdmin={auth.isAdmin}
          myBookingIds={myBookingIds}
          query={query}
          filter={filter}
          onBook={startBooking}
          onBookEmergency={startEmergencyBooking}
          onOpenBooking={(id) => void openBooking(id)}
          onToggleFreeze={(day, slot) => void toggleSlotFreeze(day, slot)}
        />

        <footer className="pt-2 pb-6 text-center text-xs text-ink-muted">
          All times shown in {timezone.replace('_', ' ')}. Authentication, ownership and tenant-specific
          weekly limits are enforced by the server. Today and all past deployment dates are permanently
          read-only; upcoming freeze dates come from Booking Rules. Normal deployment days are Sunday through Thursday.
        </footer>
      </main>

      <BookingDrawer
        open={bookingDrawerOpen}
        onClose={() => {
          setBookingDrawerOpen(false)
          setCreateTarget(null)
          setEditBooking(null)
        }}
        settings={settings}
        isAdmin={auth.isAdmin}
        createTarget={createTarget}
        editBooking={editBooking}
        onSaved={refreshAll}
      />

      <BookingDetailsDrawer
        open={detailOpen}
        onClose={() => {
          setDetailOpen(false)
          setDetailBooking(null)
        }}
        booking={detailBooking}
        loading={detailLoading}
        settings={settings}
        isAdmin={auth.isAdmin}
        userId={user.id}
        timezone={timezone}
        onEdit={startEdit}
        onChanged={refreshAll}
      />

      <ProfileModal open={profileOpen} onClose={() => setProfileOpen(false)} user={user} />

      {auth.isAdmin ? (
        <AdminPanel
          open={adminPanelOpen}
          onClose={() => setAdminPanelOpen(false)}
          timezone={timezone}
          onChanged={refreshAll}
          onOpenBooking={(id) => {
            setAdminPanelOpen(false)
            void openBooking(id)
          }}
        />
      ) : null}
    </div>
  )
}
