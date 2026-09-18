import { useCallback, useEffect, useMemo, useState } from 'react'
import { AdminLoginModal } from './components/AdminLoginModal'
import { AdminPanel } from './components/AdminPanel'
import { AppHeader } from './components/AppHeader'
import { BookingDetailsDrawer } from './components/BookingDetailsDrawer'
import { BookingDrawer } from './components/BookingDrawer'
import { Alert } from './components/Icons'
import { MyBookingsModal } from './components/MyBookingsModal'
import { OwnerVerificationModal } from './components/OwnerVerificationModal'
import { ScheduleFilters } from './components/ScheduleFilters'
import { ScheduleSummary } from './components/ScheduleSummary'
import { useToast } from './components/ToastNotification'
import { WeekNavigator } from './components/WeekNavigator'
import { matchesFilter, matchesSearch, WeeklySchedule } from './components/WeeklySchedule'
import { useAdminSession } from './hooks/useAdminSession'
import { useSchedule } from './hooks/useSchedule'
import { api, ApiError } from './services/api'
import type {
  BookingDetail,
  DayView,
  FilterKey,
  OwnerCredentials,
  PublicSettings,
  SlotView,
} from './types'
import { addDays, toIsoDate, weekStart } from './utils/dates'

const FALLBACK_SETTINGS: PublicSettings = {
  weekly_booking_limit: 2,
  booking_freeze_hours: 48,
  max_file_size_mb: 20,
  mandatory_documents: [],
  document_catalog: [],
  technologies: ['Databricks', 'AzDF', 'Database', 'Application', 'Infrastructure', 'Other'],
}

/** Reads `/booking/manage/<token>` so a management link opens that booking. */
function manageTokenFromUrl(): string | null {
  const match = window.location.pathname.match(/^\/booking\/manage\/([^/]+)\/?$/)
  return match ? decodeURIComponent(match[1]!) : null
}

export default function App() {
  const toast = useToast()
  const admin = useAdminSession()

  const [anchor, setAnchor] = useState(() => weekStart(toIsoDate(new Date())))
  const { schedule, loading, error, refresh } = useSchedule(anchor)
  const settings = schedule?.settings ?? FALLBACK_SETTINGS
  const timezone = schedule?.timezone ?? 'Asia/Kolkata'

  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<FilterKey>('ALL')

  // Ownership proven this session: booking id -> credentials + manage token.
  const [ownedBookings, setOwnedBookings] = useState<
    Map<number, { credentials: OwnerCredentials; manageToken: string | null }>
  >(new Map())

  const [createTarget, setCreateTarget] = useState<{ day: DayView; slot: SlotView } | null>(null)
  const [editBooking, setEditBooking] = useState<BookingDetail | null>(null)
  const [bookingDrawerOpen, setBookingDrawerOpen] = useState(false)

  const [detailBooking, setDetailBooking] = useState<BookingDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailOpen, setDetailOpen] = useState(false)

  const [verifyFor, setVerifyFor] = useState<{ id: number; reason: string } | null>(null)
  const [myBookingsOpen, setMyBookingsOpen] = useState(false)
  const [adminLoginOpen, setAdminLoginOpen] = useState(false)
  const [adminPanelOpen, setAdminPanelOpen] = useState(false)

  const myBookingIds = useMemo(() => new Set(ownedBookings.keys()), [ownedBookings])

  const rememberOwnership = useCallback(
    (bookingId: number, credentials: OwnerCredentials, manageToken: string | null) => {
      setOwnedBookings((current) => new Map(current).set(bookingId, { credentials, manageToken }))
    },
    [],
  )

  const openBooking = useCallback(async (bookingId: number) => {
    setDetailOpen(true)
    setDetailLoading(true)
    try {
      setDetailBooking(await api.getBooking(bookingId))
    } catch (caught) {
      toast.error('Could not load the booking', caught instanceof ApiError ? caught.message : '')
      setDetailOpen(false)
    } finally {
      setDetailLoading(false)
    }
    // toast is stable for the lifetime of the provider
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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

  // A /booking/manage/<token> link opens that booking with ownership proven.
  useEffect(() => {
    const token = manageTokenFromUrl()
    if (!token) return
    api
      .getBookingByToken(token)
      .then((booking) => {
        setOwnedBookings((current) =>
          new Map(current).set(booking.id, {
            credentials: { requester_email: booking.requester_email, booking_pin: '' },
            manageToken: token,
          }),
        )
        setAnchor(weekStart(booking.deployment_date))
        setDetailBooking(booking)
        setDetailOpen(true)
        toast.info('Opened from your management link.', booking.booking_reference)
      })
      .catch(() => toast.error('That management link is no longer valid.'))
    window.history.replaceState({}, '', '/')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const visibleCount = useMemo(() => {
    if (!schedule) return null
    if (!query.trim() && filter === 'ALL') return null
    return schedule.days.reduce(
      (total, day) =>
        total +
        day.slots.filter(
          (slot) => matchesSearch(slot, query) && matchesFilter(slot, filter, myBookingIds),
        ).length,
      0,
    )
  }, [schedule, query, filter, myBookingIds])

  function startBooking(day: DayView, slot: SlotView) {
    if (slot.is_emergency && !admin.isAdmin) {
      toast.locked(
        'Emergency slot is administrator only',
        'Slot 5 is reserved for emergency changes. Contact an administrator.',
      )
      return
    }
    setEditBooking(null)
    setCreateTarget({ day, slot })
    setBookingDrawerOpen(true)
  }

  function startEdit(booking: BookingDetail) {
    if (admin.isAdmin) {
      setCreateTarget(null)
      setEditBooking(booking)
      setBookingDrawerOpen(true)
      return
    }
    const owned = ownedBookings.get(booking.id)
    if (owned && owned.credentials.booking_pin) {
      setCreateTarget(null)
      setEditBooking(booking)
      setBookingDrawerOpen(true)
      return
    }
    setVerifyFor({ id: booking.id, reason: 'Confirm your PIN before editing this booking.' })
  }

  const detailOwnership = detailBooking ? ownedBookings.get(detailBooking.id) : undefined
  const editOwnership = editBooking ? ownedBookings.get(editBooking.id) : undefined
  const currentWeek = anchor === weekStart(toIsoDate(new Date()))

  return (
    <div className="min-h-dvh">
      <AppHeader
        timezone={timezone}
        adminUsername={admin.username}
        onAdminLogin={() => setAdminLoginOpen(true)}
        onAdminPanel={() => setAdminPanelOpen(true)}
        onAdminLogout={() => {
          void admin.signOut().then(() => {
            setAdminPanelOpen(false)
            refresh()
            toast.info('Signed out of the administrator session.')
          })
        }}
        onMyBookings={() => setMyBookingsOpen(true)}
        weekNavigator={
          <WeekNavigator
            label={schedule?.week_label ?? '—'}
            loading={loading}
            isCurrentWeek={currentWeek}
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
            myBookingCount={
              schedule.days.reduce(
                (total, day) =>
                  total +
                  day.slots.filter((slot) => slot.booking && myBookingIds.has(slot.booking.id)).length,
                0,
              )
            }
            onShowMine={() => setMyBookingsOpen(true)}
          />
        ) : null}

        <ScheduleFilters
          query={query}
          onQueryChange={setQuery}
          filter={filter}
          onFilterChange={setFilter}
          technologies={settings.technologies}
          isAdmin={admin.isAdmin}
          resultCount={visibleCount}
        />

        <WeeklySchedule
          schedule={schedule}
          loading={loading}
          isAdmin={admin.isAdmin}
          myBookingIds={myBookingIds}
          query={query}
          filter={filter}
          onBook={startBooking}
          onOpenBooking={(id) => void openBooking(id)}
        />

        <footer className="pt-2 pb-6 text-center text-xs text-ink-muted">
          All times shown in {timezone.replace('_', ' ')}. Slot availability, ownership and the{' '}
          {settings.booking_freeze_hours}-hour freeze window are enforced by the server.
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
        isAdmin={admin.isAdmin}
        createTarget={createTarget}
        editBooking={editBooking}
        credentials={editOwnership?.credentials ?? null}
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
        isAdmin={admin.isAdmin}
        timezone={timezone}
        credentials={detailOwnership?.credentials ?? null}
        manageToken={detailOwnership?.manageToken ?? null}
        onEdit={startEdit}
        onRequestVerification={(booking) =>
          setVerifyFor({
            id: booking.id,
            reason: 'Enter the requester email and PIN used when this slot was booked.',
          })
        }
        onChanged={refreshAll}
      />

      <OwnerVerificationModal
        open={verifyFor !== null}
        onClose={() => setVerifyFor(null)}
        bookingId={verifyFor?.id ?? null}
        reason={verifyFor?.reason ?? ''}
        onVerified={(booking, credentials, manageToken) => {
          rememberOwnership(booking.id, credentials, manageToken)
          setDetailBooking(booking)
          setDetailOpen(true)
        }}
      />

      <MyBookingsModal
        open={myBookingsOpen}
        onClose={() => setMyBookingsOpen(false)}
        onFound={(bookings, credentials) => {
          setOwnedBookings((current) => {
            const next = new Map(current)
            for (const booking of bookings) {
              next.set(booking.id, { credentials, manageToken: next.get(booking.id)?.manageToken ?? null })
            }
            return next
          })
        }}
        onOpenBooking={(id) => void openBooking(id)}
      />

      <AdminLoginModal
        open={adminLoginOpen}
        onClose={() => setAdminLoginOpen(false)}
        onLoggedIn={(session) => {
          admin.signIn(session)
          refresh()
        }}
      />

      {admin.isAdmin ? (
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
