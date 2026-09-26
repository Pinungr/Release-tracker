import { useCallback, useEffect, useMemo, useState } from 'react'
import { AdminGroupManager } from './components/AdminGroupManager'
import { AdminPanel } from './components/AdminPanel'
import { AppFooter } from './components/AppFooter'
import { AppHeader } from './components/AppHeader'
import { ChangeDetailsPage } from './components/ChangeDetailsPage'
import { BookingDrawer, type CreateTarget } from './components/BookingDrawer'
import { Alert, Spinner } from './components/Icons'
import { LandingBanner } from './components/LandingBanner'
import { ProfileModal } from './components/ProfileModal'
import { RequiredPasswordChangeScreen } from './components/RequiredPasswordChangeScreen'
import { ScheduleSearch } from './components/ScheduleSearch'
import { ScheduleFilters } from './components/ScheduleFilters'
import { ScheduleSummary } from './components/ScheduleSummary'
import { SignInScreen } from './components/SignInScreen'
import { useToast } from './components/ToastNotification'
import { WeekNavigator } from './components/WeekNavigator'
import { matchesFilter, matchesSearch, WeeklySchedule } from './components/WeeklySchedule'
import { useAuthSession } from './hooks/useAuthSession'
import { useCloneMode } from './hooks/useCloneMode'
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
  let content

  if (auth.checking) {
    content = (
      <div className="grid flex-1 place-items-center text-sm text-ink-muted">
        <span className="inline-flex items-center gap-3">
          <Spinner className="size-5" />
          Restoring your session…
        </span>
      </div>
    )
  } else if (!auth.isAuthenticated) {
    content = <SignInScreen onSignedIn={auth.signIn} />
  } else if (auth.user?.must_change_password) {
    content = (
      <RequiredPasswordChangeScreen
        user={auth.user}
        onChanged={auth.refreshUser}
        onLogout={() => void auth.signOut()}
      />
    )
  } else {
    // Remounting on identity change clears every cached booking and filter from
    // the previous session.
    content = <Scheduler key={auth.user!.id} auth={auth} />
  }

  return (
    <div className="flex min-h-dvh flex-col">
      {content}
      <AppFooter />
    </div>
  )
}

function Scheduler({ auth }: { auth: ReturnType<typeof useAuthSession> }) {
  const toast = useToast()
  const user = auth.user!

  const [anchor, setAnchor] = useState(() => auth.isAdmin ? weekStart(toIsoDate(new Date())) : '')
  const { schedule, loading, error, refresh } = useSchedule(anchor)
  const settings = schedule?.settings ?? FALLBACK_SETTINGS
  const timezone = schedule?.timezone ?? 'Asia/Kolkata'

  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<FilterKey>('ALL')

  const [createTarget, setCreateTarget] = useState<CreateTarget | null>(null)
  const setBoardView = useCallback((next: { filter: FilterKey; query: string }) => {
    setFilter(next.filter)
    setQuery(next.query)
  }, [])
  const { cloneSource, startClone, endClone } = useCloneMode({ filter, query }, setBoardView)
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

  const [route, setRoute] = useState(() => window.location.hash)
  const groupsOpen = /^#\/admin\/groups(?:\/|$)/.test(route)
  const closeDetails = useCallback(() => { window.location.hash = '' }, [])
  const openBooking = useCallback((id: number) => { window.location.hash = `change/${id}` }, [])
  useEffect(() => {
    const onHash = () => setRoute(window.location.hash)
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  useEffect(() => {
    const match = /^#change\/(\d+)$/.exec(route)
    setDetailBooking(null)
    setDetailOpen(Boolean(match))
    if (!match) return
    window.scrollTo(0, 0)
    let active = true
    setDetailLoading(true)
    api.getBooking(Number(match[1])).then(booking => {
      if (active) setDetailBooking(booking)
    }).catch(caught => {
      if (active) {
        toast.error('Could not open the change record', caught instanceof ApiError ? caught.message : 'Please try again.')
        closeDetails()
      }
    }).finally(() => { if (active) setDetailLoading(false) })
    return () => { active = false }
  }, [route, closeDetails, toast])

  /** After any mutation, refresh both the board and the open detail drawer. */
  const refreshAll = useCallback(() => {
    refresh()
    if (detailBooking) {
      void api
        .getBooking(detailBooking.id)
        .then(updated => setDetailBooking(current => current?.id === updated.id ? updated : current))
        .catch(() => undefined)
    }
  }, [refresh, detailBooking])

  function startBooking(day: DayView, slot: SlotView) {
    if (!schedule || day.is_past || day.day <= schedule.today) {
      toast.locked('Date is read-only', 'Past and current deployment dates cannot be booked or modified by any user, including the Owner or Release Managers.')
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
        toast.locked(`Slot ${slot.slot_number} frozen`, 'Tenant users can no longer book or edit this slot. Owner/Release Manager access remains available.')
      }
      refreshAll()
    } catch (caught) {
      toast.error(
        slot.manually_frozen ? 'Could not unfreeze the slot' : 'Could not freeze the slot',
        caught instanceof ApiError ? caught.message : '',
      )
    }
  }

  /**
   * Adds or removes one normal deployment slot on a single date. The default
   * count in Booking Rules still governs every other date.
   */
  async function adjustDayCapacity(day: DayView, delta: 1 | -1) {
    if (!auth.isAdmin || !schedule || day.is_past || day.day <= schedule.today) return
    try {
      const capacity = delta === 1 ? await api.addDaySlot(day.day) : await api.removeDaySlot(day.day)
      toast.success(
        delta === 1 ? 'Slot added' : 'Slot removed',
        `${day.weekday} ${day.date_label} now has ${capacity.slot_count} normal slot${
          capacity.slot_count === 1 ? '' : 's'
        }.`,
      )
      refreshAll()
    } catch (caught) {
      toast.error(
        delta === 1 ? 'Could not add a slot' : 'Could not remove a slot',
        caught instanceof ApiError ? caught.message : '',
      )
    }
  }

  function startEmergencyBooking(day: DayView) {
    if (!schedule || day.is_past || day.day <= schedule.today) {
      toast.locked('Date is read-only', 'Past and current deployment dates cannot accept emergency changes, including for the Owner or Release Managers.')
      return
    }
    if (!auth.isAdmin) {
      toast.locked(
        'Emergency changes are restricted',
        'Contact the Owner or a Release Manager to raise an emergency change.',
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
          ? 'Past deployment records cannot be edited by any user, including the Owner or Release Managers.'
          : 'This booking is inside a protected date or slot freeze window.',
      )
      return
    }
    if (!auth.isAdmin && booking.created_by_user_id !== user.id) {
      toast.error('You are not authorized to edit this change record.')
      return
    }
    // Hand over from the details drawer to the edit drawer rather than
    // stacking them: both are full-height panels at the same depth, so leaving
    // details open would cover the edit form.
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
    <div className="flex flex-1 flex-col">
      <AppHeader
        timezone={timezone}
        username={user.username}
        isAdmin={auth.isAdmin}
        isOwner={user.is_owner === true}
        onProfile={() => setProfileOpen(true)}
        onAdminPanel={() => setAdminPanelOpen(true)}
        onLogout={() => void auth.signOut()}
        groupsOpen={groupsOpen}
        weekNavigator={detailOpen || groupsOpen ? null : (
          <WeekNavigator
            label={schedule?.week_label ?? '—'}
            loading={loading}
            isCurrentWeek={(schedule?.week_start ?? anchor) === weekStart(toIsoDate(new Date()))}
            onPrevious={() => setAnchor(addDays(schedule?.week_start || anchor, -7))}
            onNext={() => setAnchor(addDays(schedule?.week_start || anchor, 7))}
            onToday={() => setAnchor(weekStart(toIsoDate(new Date())))}
          />
        )}
      />

      {!groupsOpen && <ScheduleSearch onOpen={openBooking} />}
      {groupsOpen && (auth.isAdmin ? <AdminGroupManager isOwner={user.is_owner === true} route={route} /> : <main className="mx-auto my-10 max-w-lg card p-8 text-center"><h1 className="text-xl font-semibold">Group management is restricted</h1><p className="mt-2 text-sm text-ink-muted">Contact your organization owner for help with group membership.</p><a href="#" className="btn-primary mt-5">Back to schedule</a></main>)}
      {!detailOpen && !groupsOpen && <main className="mx-auto w-full max-w-[88rem] flex-1 space-y-4 px-4 py-5 sm:px-6 lg:px-8">
        {cloneSource && <div className="card flex flex-wrap items-center gap-3 border-blue-200 bg-blue-50 p-4">
          <p className="flex-1 text-sm text-blue-900">Cloning <strong>{cloneSource.booking_reference}</strong>. Choose an available slot, review the details, and upload fresh required documents.</p>
          <button className="btn-secondary" onClick={endClone}>Cancel clone</button>
        </div>}
        {error ? (
          <div className="card flex flex-wrap items-center gap-3 border-rose-200 bg-rose-50 p-4">
            <Alert className="size-5 text-rose-600" />
            <p className="text-sm text-rose-900">{error}</p>
            <button type="button" className="btn-secondary btn-sm ml-auto" onClick={refresh}>
              Retry
            </button>
          </div>
        ) : null}

        {schedule ? <LandingBanner schedule={schedule} onGoToWeek={setAnchor} /> : null}

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
          onAdjustCapacity={(day, delta) => void adjustDayCapacity(day, delta)}
        />

      </main>}

      <BookingDrawer
        open={bookingDrawerOpen}
        onClose={() => {
          setBookingDrawerOpen(false)
          setCreateTarget(null)
          setEditBooking(null)
          endClone()
        }}
        settings={settings}
        isAdmin={auth.isAdmin}
        createTarget={createTarget}
        editBooking={editBooking}
        cloneSource={editBooking ? null : cloneSource}
        onSaved={refreshAll}
      />

      <ChangeDetailsPage
        open={detailOpen}
        onClose={closeDetails}
        booking={detailBooking}
        loading={detailLoading}
        settings={settings}
        isAdmin={auth.isAdmin}
        userId={user.id}
        timezone={timezone}
        onClone={(source) => {
          startClone(source)
          closeDetails()
        }}
        onEdit={startEdit}
        onChanged={refreshAll}
      />

      <ProfileModal open={profileOpen} onClose={() => setProfileOpen(false)} user={user} />

      {auth.isAdmin ? (
        <AdminPanel
          open={adminPanelOpen}
          onClose={() => setAdminPanelOpen(false)}
          timezone={timezone}
          currentUserId={user.id}
          isOwner={user.is_owner === true}
          onChanged={refreshAll}
        />
      ) : null}
    </div>
  )
}
