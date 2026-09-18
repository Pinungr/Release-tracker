/**
 * Thin REST client. The authenticated account bearer token lives in sessionStorage.
 */
import type {
  AuthSession,
  AuthUser,
  AdminSettings,
  AdminTenant,
  AuditEvent,
  BookingCreated,
  BookingDetail,
  BookingSummary,
  DailyOverride,
  DocumentCategory,
  Holiday,
  ManagedUser,
  Schedule,
  SlotConfig,
  Tenant,
} from '../types'

const BASE = '/api'
const TOKEN_KEY = 'pds.user.token'

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export const userToken = {
  get: (): string | null => sessionStorage.getItem(TOKEN_KEY),
  set: (token: string) => sessionStorage.setItem(TOKEN_KEY, token),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
}

function authHeaders(): Record<string, string> {
  const token = userToken.get()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** Turns FastAPI's error shapes into a single readable sentence. */
async function readError(response: Response): Promise<string> {
  let detail: unknown
  try {
    detail = (await response.json())?.detail
  } catch {
    detail = null
  }
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item: { loc?: unknown[]; msg?: string }) => {
        const field = Array.isArray(item.loc) ? String(item.loc[item.loc.length - 1]) : ''
        const label = field
          .replace(/_/g, ' ')
          .replace(/\b\w/g, (c) => c.toUpperCase())
        const msg = (item.msg ?? '').replace(/^Value error,\s*/, '')
        return field && !msg.includes(label) ? `${label}: ${msg}` : msg
      })
      .filter(Boolean)
    if (messages.length) return messages.join('\n')
  }
  if (response.status === 401) return 'Your session has expired. Please sign in again.'
  return `Request failed (${response.status}).`
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...(init.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...authHeaders(),
      ...(init.headers ?? {}),
    },
  })
  if (!response.ok) {
    if (response.status === 401) userToken.clear()
    throw new ApiError(await readError(response), response.status)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

const json = (body: unknown) => JSON.stringify(body)

async function download(path: string, filename: string): Promise<void> {
  const response = await fetch(`${BASE}${path}`, { headers: authHeaders() })
  if (!response.ok) {
    if (response.status === 401) userToken.clear()
    throw new ApiError(await readError(response), response.status)
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export const api = {
  // ---- public -------------------------------------------------------------
  getSchedule: (weekAnchor: string) => request<Schedule>(`/schedule?week=${weekAnchor}`),

  login: (username_or_email: string, password: string) =>
    request<AuthSession>('/auth/login', { method: 'POST', body: json({ username_or_email, password }) }),

  register: (payload: Record<string, unknown>) =>
    request<{ user: AuthUser }>('/auth/register', { method: 'POST', body: json(payload) }),

  me: () => request<AuthUser>('/auth/me'),

  changePassword: async (payload: Record<string, unknown>) => {
    const response = await request<{
      message: string
      access_token: string
      token_type: string
      expires_in: number
    }>('/auth/me/change-password', { method: 'POST', body: json(payload) })
    // The server increments token_version during a password change, making
    // every older JWT invalid. Keep only the freshly issued replacement.
    userToken.set(response.access_token)
    return response
  },

  getActiveTenants: () => request<Tenant[]>('/tenants/active'),

  getBooking: (id: number) => request<BookingDetail>(`/bookings/${id}`),

  createBooking: (
    payload: Record<string, unknown>,
    documents: Partial<Record<DocumentCategory, File[]>>,
  ) => {
    const form = new FormData()
    form.append('payload', JSON.stringify(payload))
    for (const [category, files] of Object.entries(documents) as [DocumentCategory, File[]][]) {
      for (const file of files ?? []) form.append(`document_${category}`, file)
    }
    return request<BookingCreated>('/bookings', { method: 'POST', body: form })
  },

  updateBooking: (id: number, payload: Record<string, unknown>) =>
    request<BookingDetail>(`/bookings/${id}`, { method: 'PUT', body: json(payload) }),

  cancelBooking: (id: number, payload: Record<string, unknown>) =>
    request<BookingSummary>(`/bookings/${id}`, { method: 'DELETE', body: json(payload) }),

  startWork: (id: number, change_number: string) =>
    request<BookingDetail>(`/bookings/${id}/start-work`, {
      method: 'POST',
      body: json({ change_number }),
    }),

  uploadAttachment: (id: number, category: DocumentCategory, file: File) => {
    const form = new FormData()
    form.append('category', category)
    form.append('file', file)
    return request<BookingDetail>(`/bookings/${id}/attachments`, { method: 'POST', body: form })
  },

  deleteAttachment: (id: number, attachmentId: number) =>
    request<BookingDetail>(`/bookings/${id}/attachments/${attachmentId}`, {
      method: 'DELETE',
      body: '{}',
    }),

  downloadAttachment: (id: number, attachmentId: number, filename: string) =>
    download(`/bookings/${id}/attachments/${attachmentId}/download`, filename),

  // ---- admin --------------------------------------------------------------
  logout: () => request<void>('/auth/logout', { method: 'POST' }),

  getSettings: () => request<AdminSettings>('/admin/settings'),

  updateSettings: (payload: Partial<AdminSettings>) =>
    request<AdminSettings>('/admin/settings', { method: 'PUT', body: json(payload) }),

  getSlots: () => request<SlotConfig[]>('/admin/slots'),

  replaceSlots: (slots: SlotConfig[]) =>
    request<SlotConfig[]>('/admin/slots', { method: 'PUT', body: json({ slots }) }),

  getHolidays: () => request<Holiday[]>('/admin/holidays'),

  createHoliday: (payload: Omit<Holiday, 'id'>) =>
    request<Holiday>('/admin/holidays', { method: 'POST', body: json(payload) }),

  updateHoliday: (id: number, payload: Omit<Holiday, 'id'>) =>
    request<Holiday>(`/admin/holidays/${id}`, { method: 'PUT', body: json(payload) }),

  deleteHoliday: (id: number) => request<void>(`/admin/holidays/${id}`, { method: 'DELETE' }),

  getOverrides: () => request<DailyOverride[]>('/admin/overrides'),

  upsertOverride: (payload: Omit<DailyOverride, 'id'>) =>
    request<DailyOverride>('/admin/overrides', { method: 'PUT', body: json(payload) }),

  deleteOverride: (id: number) => request<void>(`/admin/overrides/${id}`, { method: 'DELETE' }),

  freezeSlot: (freeze_date: string, slot_number: number, note?: string) =>
    request<{ id: number; freeze_date: string; slot_number: number; note: string | null }>(
      '/admin/slot-freezes',
      { method: 'POST', body: json({ freeze_date, slot_number, note: note ?? null }) },
    ),

  unfreezeSlot: (freeze_date: string, slot_number: number) =>
    request<void>(`/admin/slot-freezes/${freeze_date}/${slot_number}`, { method: 'DELETE' }),

  listBookings: (includeCancelled = false) =>
    request<BookingSummary[]>(`/admin/bookings?include_cancelled=${includeCancelled}`),

  moveBooking: (id: number, payload: Record<string, unknown>) =>
    request<BookingDetail>(`/admin/bookings/${id}/move`, { method: 'POST', body: json(payload) }),

  reassignBooking: (id: number, payload: Record<string, unknown>) =>
    request<BookingDetail>(`/admin/bookings/${id}/reassign`, {
      method: 'POST',
      body: json(payload),
    }),

  assignBookingUsers: (id: number, user_ids: number[]) =>
    request<BookingDetail>(`/admin/bookings/${id}/assign-users`, {
      method: 'POST',
      body: json({ user_ids }),
    }),

  setBookingStatus: (id: number, status: string, overrideReason?: string) =>
    request<BookingDetail>(`/admin/bookings/${id}/status`, {
      method: 'POST',
      body: json({ status, override_reason: overrideReason ?? null }),
    }),

  deleteBooking: (id: number) => request<void>(`/admin/bookings/${id}`, { method: 'DELETE' }),

  getAudit: (bookingId?: number) =>
    request<AuditEvent[]>(`/admin/audit${bookingId ? `?booking_id=${bookingId}` : ''}`),

  // ---- admin: people and tenants -------------------------------------------
  listUsers: (search?: string) =>
    request<ManagedUser[]>(`/admin/users${search ? `?search=${encodeURIComponent(search)}` : ''}`),

  setUserRole: (id: number, role: 'ADMIN' | 'TENANT_USER') =>
    request<{ role: string }>(`/admin/users/${id}/role`, {
      method: 'PATCH',
      body: json({ role }),
    }),

  setUserActive: (id: number, is_active: boolean) =>
    request<{ is_active: boolean }>(`/admin/users/${id}/status`, {
      method: 'PATCH',
      body: json({ is_active }),
    }),

  resetUserPassword: (id: number, new_password: string, confirm_new_password: string) =>
    request<{ message: string }>(`/admin/users/${id}/reset-password`, {
      method: 'POST',
      body: json({ new_password, confirm_new_password }),
    }),

  listAdminTenants: () => request<AdminTenant[]>('/admin/tenants'),

  createAdminTenant: (payload: Record<string, unknown>) =>
    request<AdminTenant>('/admin/tenants', { method: 'POST', body: json(payload) }),

  updateAdminTenant: (id: number, payload: Record<string, unknown>) =>
    request<AdminTenant>(`/admin/tenants/${id}`, { method: 'PUT', body: json(payload) }),

  setTenantActive: (id: number, is_active: boolean) =>
    request<AdminTenant>(`/admin/tenants/${id}/status`, {
      method: 'PATCH',
      body: json({ is_active }),
    }),
}
