/**
 * Thin REST client. The authenticated account bearer token lives in sessionStorage.
 */
import type {
  AuthSession,
  AuthUser,
  AccessGroup,
  GroupMember,
  AdminSettings,
  AdminTenant,
  AuditEvent,
  BookingComment,
  CommentImage,
  CommentImageRef,
  ScheduleSearchResult,
  BookingCreated,
  BookingDetail,
  BookingSummary,
  DaySlotCapacity,
  DocumentCategory,
  Holiday,
  ManagedUser,
  Schedule,
  SlotConfig,
  SlotOption,
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
  getSchedule: (weekAnchor: string, firstAvailable = false) => request<Schedule>(`/schedule?week=${weekAnchor}&first_available=${firstAvailable}`),

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

  getRescheduleOptions: (id: number) =>
    request<SlotOption[]>(`/bookings/${id}/reschedule-options`),

  rescheduleBooking: (id: number, deployment_date: string, slot_number: number) =>
    request<BookingDetail>(`/bookings/${id}/reschedule`, {
      method: 'POST',
      body: json({ deployment_date, slot_number, override_reason: null }),
    }),

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

  // Per-date normal slot capacity. The default comes from Booking Rules;
  // these adjust one date without disturbing any other.
  addDaySlot: (day: string) =>
    request<DaySlotCapacity>(`/admin/day-capacity/${day}/add-slot`, { method: 'POST' }),

  removeDaySlot: (day: string) =>
    request<DaySlotCapacity>(`/admin/day-capacity/${day}/remove-slot`, { method: 'POST' }),

  freezeSlot: (freeze_date: string, slot_number: number, note?: string) =>
    request<{ id: number; freeze_date: string; slot_number: number; note: string | null }>(
      '/admin/slot-freezes',
      { method: 'POST', body: json({ freeze_date, slot_number, note: note ?? null }) },
    ),

  unfreezeSlot: (freeze_date: string, slot_number: number) =>
    request<void>(`/admin/slot-freezes/${freeze_date}/${slot_number}`, { method: 'DELETE' }),

  moveBooking: (id: number, payload: Record<string, unknown>) =>
    request<BookingDetail>(`/admin/bookings/${id}/move`, { method: 'POST', body: json(payload) }),

  searchReleaseManagers: (q: string) =>
    request<GroupMember[]>(`/admin/release-managers/search?q=${encodeURIComponent(q)}`),

  assignBookingUsers: (id: number, user_ids: number[]) =>
    request<BookingDetail>(`/admin/bookings/${id}/assign-users`, {
      method: 'POST',
      body: json({ user_ids }),
    }),

  assignBookingToMe: (id: number) =>
    request<BookingDetail>(`/admin/bookings/${id}/assign-self`, { method: 'POST' }),

  setBookingStatus: (id: number, status: string, overrideReason?: string) =>
    request<BookingDetail>(`/admin/bookings/${id}/status`, {
      method: 'POST',
      body: json({ status, override_reason: overrideReason ?? null }),
    }),

  searchSchedules: (q: string, beforeId?: number) => request<ScheduleSearchResult[]>(`/bookings/search?q=${encodeURIComponent(q)}${beforeId ? `&before_id=${beforeId}` : ''}`),
  downloadCommentAttachment: (bookingId: number, commentId: number, attachmentId: string, filename: string) =>
    download(`/bookings/${bookingId}/comments/${commentId}/attachments/${encodeURIComponent(attachmentId)}`, filename),
  uploadComment: (id: number, body: string, internal: boolean, files: File[], imageRefs: CommentImageRef[] = []) => {
    const form = new FormData()
    form.append('body', body)
    form.append('internal', String(internal))
    form.append('image_refs', JSON.stringify(imageRefs))
    files.forEach(file => form.append('files', file))
    return request<BookingComment>(`/bookings/${id}/comments/upload`, { method: 'POST', body: form })
  },
  listCommentImages: (id: number, internal: boolean, beforeId?: number) =>
    request<{images: CommentImage[]; next_before_id: number | null}>(`/bookings/${id}/comment-images?internal=${internal}${beforeId ? `&before_id=${beforeId}` : ''}`),
  getCommentImage: async (id: number, image: CommentImageRef, signal?: AbortSignal): Promise<Blob> => {
    const params = new URLSearchParams({kind: image.kind, attachment_id: image.attachment_id})
    if (image.comment_id) params.set('comment_id', String(image.comment_id))
    const response = await fetch(`${BASE}/bookings/${id}/comment-images/preview?${params}`, {headers: authHeaders(), signal})
    if (!response.ok) throw new ApiError(await readError(response), response.status)
    const blob = await response.blob()
    if (!['image/png', 'image/jpeg'].includes(blob.type)) throw new ApiError('Image preview unavailable.', 415)
    return blob
  },
  getBookingComments: (id: number, beforeId?: number) =>
    request<BookingComment[]>(`/bookings/${id}/comments${beforeId ? `?before_id=${beforeId}` : ''}`),
  getCollaboratorCandidates: (id: number, q?: string) =>
    request<Array<{ id: number; full_name: string; username: string; email: string; selected: boolean }>>(`/bookings/${id}/collaborator-candidates${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  setCollaborators: (id: number, user_ids: number[]) =>
    request<BookingDetail>(`/bookings/${id}/collaborators`, { method: 'PUT', body: json({ user_ids }) }),
  addBookingComment: (id: number, body: string, internal: boolean, imageRefs: CommentImageRef[] = []) =>
    request<BookingComment>(`/bookings/${id}/comments`, { method: 'POST', body: JSON.stringify({ body, internal, image_refs: imageRefs }) }),
  getBookingAudit: (id: number, beforeId?: number) =>
    request<AuditEvent[]>(`/bookings/${id}/audit${beforeId ? `?before_id=${beforeId}` : ''}`),
  getBookingByReference: (reference: string) =>
    request<BookingDetail>(`/bookings/by-reference/${encodeURIComponent(reference)}`),
  getAudit: (filters: { bookingId?: number; q?: string; eventType?: string; actorType?: 'USER' | 'ADMIN' | 'SYSTEM'; beforeId?: number; limit?: number } = {}) => {
    const params = new URLSearchParams()
    if (filters.bookingId) params.set('booking_id', String(filters.bookingId))
    if (filters.q?.trim()) params.set('q', filters.q.trim())
    if (filters.eventType) params.set('event_type', filters.eventType)
    if (filters.actorType) params.set('actor_type', filters.actorType)
    if (filters.beforeId) params.set('before_id', String(filters.beforeId))
    if (filters.limit) params.set('limit', String(filters.limit))
    const query = params.toString()
    return request<AuditEvent[]>(`/admin/audit${query ? `?${query}` : ''}`)
  },

  // ---- admin: people and tenants -------------------------------------------
  listUsers: (search?: string) =>
    request<ManagedUser[]>(`/admin/users${search ? `?search=${encodeURIComponent(search)}` : ''}`),

  listGroups: () => request<AccessGroup[]>('/admin/groups'),
  getGroup: (id: number, search?: string) => request<AccessGroup>(`/admin/groups/${id}${search ? `?search=${encodeURIComponent(search)}` : ''}`),
  createGroup: (payload: { name: string; description?: string; permissions?: Record<string, boolean> }) =>
    request<AccessGroup>('/admin/groups', { method: 'POST', body: json(payload) }),
  updateGroup: (id: number, payload: Record<string, unknown>) =>
    request<AccessGroup>(`/admin/groups/${id}`, { method: 'PUT', body: json(payload) }),
  deleteGroup: (id: number) => request<void>(`/admin/groups/${id}`, { method: 'DELETE' }),
  addGroupMember: (groupId: number, userId: number) =>
    request<AccessGroup>(`/admin/groups/${groupId}/members/${userId}`, { method: 'POST' }),
  removeGroupMember: (groupId: number, userId: number) =>
    request<AccessGroup>(`/admin/groups/${groupId}/members/${userId}`, { method: 'DELETE' }),

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
