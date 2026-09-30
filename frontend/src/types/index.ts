/** Mirrors the FastAPI response schemas. Nothing here is hard-coded data. */

/** Key of an Admin/RM-configured document type (see DocumentTypeConfig). */
export type DocumentCategory = string

export type SlotState =
  | 'AVAILABLE'
  | 'BOOKED'
  | 'HOLIDAY'
  | 'DISABLED'

export type BookingStatus =
  | 'BOOKED'
  | 'LOCKED'
  | 'IN_PROGRESS'
  | 'COMPLETED'
  | 'CANCELLED'
  | 'VALIDATION_PENDING'
  | 'SUCCESSFUL'
  | 'FAILED'
  | 'ROLLED_BACK'

export interface DocumentStatus {
  category: DocumentCategory
  label: string
  required: boolean
  multiple?: boolean
  provided: boolean
  file_count: number
}

export interface DocumentReadiness {
  provided_required: number
  total_required: number
  percent: number
  complete: boolean
  missing_labels: string[]
  items: DocumentStatus[]
}

export interface Attachment {
  id: number
  category: DocumentCategory
  category_label: string
  original_filename: string
  size_bytes: number
  content_type: string | null
  uploaded_at: string
  uploaded_by?: string | null
}

export interface AssignedUser {
  user_id: number
  full_name: string
  username: string
  email: string
  assigned_at: string
}

export interface BookingSummary {
  id: number
  booking_reference: string
  tenant_id: number
  tenant_name: string
  deployment_date: string
  /** null for emergency changes: they join the date's queue, not a slot. */
  slot_number: number | null
  jira_number: string | null
  jira_url: string | null
  technology: string
  environment: string
  verifier_name: string
  status: BookingStatus
  is_emergency: boolean
  created_by_user_id: number | null
  change_number: string | null
  assigned_users: AssignedUser[]
  work_started_by_user_id: number | null
  work_started_at: string | null
  is_past: boolean
  lock_reason: 'CURRENT_DATE' | 'PAST_DATE' | 'AUTOMATIC_DATE_FREEZE' | 'MANUAL_SLOT_FREEZE' | 'NONE'
  is_locked: boolean
  /** An Admin/RM unlock currently lifts the automatic lock for this record. */
  lock_overridden?: boolean
  documents: DocumentReadiness
  created_at: string
  updated_at: string
}

export interface Tenant {
  id: number
  name: string
  tenant_code: string | null
  description: string | null
  weekly_booking_limit: number | null
}

export interface BookingDetail extends BookingSummary {
  cloned_from_id?: number | null
  cloned_from_reference?: string | null
  requester_name: string
  requester_email: string
  requester_phone: string | null
  verifier_email: string
  git_repository: string
  implementation_summary: string
  deployment_description: string
  additional_comments: string | null
  justification: string
  impacted_region: string
  emergency_reason: string | null
  emergency_approval_reference: string | null
  emergency_approver: string | null
  business_justification: string | null
  cancelled_at: string | null
  cancelled_by_user_id: number | null
  attachments: Attachment[]
  collaborators: AssignedUser[]
  /** Why a non-admin caller may change this schedule. */
  access_basis?: 'SCHEDULER' | 'TENANT_MEMBER' | 'COLLABORATOR' | null
  can_edit: boolean
  can_cancel: boolean
  can_reschedule: boolean
  can_assign_rm: boolean
  can_assign_self: boolean
  can_start_work: boolean
  can_download_attachments: boolean
  can_manage_attachments: boolean
  can_manage_collaborators?: boolean
  slot_label: string
  slot_time: string
}

export interface BookingCreated {
  booking: BookingDetail
  message: string
}

export interface SlotView {
  slot_number: number
  name: string
  start_time: string
  end_time: string
  time_label: string
  enabled: boolean
  unavailable_reason: string | null
  state: SlotState
  bookable: boolean
  manually_frozen: boolean
  /** The date is inside the automatic upcoming-date lock window. */
  automatic_lock?: boolean
  /** Which Admin/RM unlock lifts the automatic lock for this slot, if any. */
  lock_override?: 'DATE' | 'SLOT' | null
  booking: BookingSummary | null
}

export interface Holiday {
  id: number
  holiday_date: string
  name: string
  description: string | null
  is_full_day: boolean
}

/** One destination offered by the reschedule picker. */
export interface SlotOption {
  deployment_date: string
  weekday: string
  date_label: string
  slot_number: number
  slot_name: string
  time_label: string
}

/** Normal slot capacity for one deployment date. */
export interface DaySlotCapacity {
  capacity_date: string
  slot_count: number
  /** null when the date follows the configured default. */
  custom_slot_count: number | null
  max_slot_count: number
}

export interface DayView {
  day: string
  weekday: string
  date_label: string
  is_today: boolean
  is_past: boolean
  holiday: Holiday | null
  /** Set only when an administrator added/removed slots on this date. */
  custom_slot_count: number | null
  regular_slots_total: number
  regular_slots_used: number
  slots: SlotView[]
  automatic_lock?: boolean
  /** An Admin/RM unlocked the whole date (every slot and the emergency queue). */
  date_unlocked?: boolean
  /** Emergency changes are an admin-only queue on the date, not a slot. */
  emergency_open: boolean
  emergency_closed_reason: string | null
  emergency_bookings: BookingSummary[]
}

export interface ScheduleSummary {
  regular_slots_total: number
  regular_slots_available: number
  slots_booked: number
  holidays: number
  /** Emergency changes scheduled this week (any number per date). */
  emergency_changes: number
}

export interface DocumentCatalogEntry {
  category: DocumentCategory
  label: string
  description?: string | null
  required: boolean
  multiple: boolean
}

/** A document upload option as Admin/RM configure it. */
export interface DocumentTypeConfig {
  id: number
  key: string
  label: string
  description: string | null
  is_active: boolean
  is_required: boolean
  allow_multiple: boolean
  display_order: number
  /** Uploaded files referencing this type; such a type can only be disabled. */
  file_count: number
  /** Schedules holding more than one file of this type (kept as they are after a switch to Single). */
  multi_file_schedules?: number
}

export interface PublicSettings {
  weekly_booking_limit: number
  /** Number of upcoming valid deployment dates protected for everyone. Today is always protected. */
  booking_freeze_dates: number
  jira_required_at_booking: boolean
  max_file_size_mb: number
  /** Active document types; `required` is the only source of mandatory documents. */
  document_catalog: DocumentCatalogEntry[]
  technologies: string[]
}

/** The earliest free normal slot, so a tenant can jump straight to it. */
export interface NextAvailableSlot {
  deployment_date: string
  /** Sunday of the week holding the slot, for board navigation. */
  week_start: string
  weekday: string
  date_label: string
  slot_number: number
  slot_name: string
  time_label: string
}

export interface Schedule {
  landing_message?: string | null
  /**
   * Only on a tenant's landing view. May sit in a later week than the one
   * shown: tenants land on the nearest week so they can see RM workload.
   */
  next_available?: NextAvailableSlot | null
  week_start: string
  week_end: string
  week_label: string
  today: string
  timezone: string
  days: DayView[]
  summary: ScheduleSummary
  settings: PublicSettings
}


export interface GroupMember {
  id: number
  full_name: string
  username: string
  email: string
  is_active: boolean
  is_owner: boolean
}

export interface AccessGroup {
  id: number
  name: string
  group_type: 'MEMBER_POOL' | 'RELEASE_MANAGERS' | 'TENANTS' | 'TENANT_SUBGROUP' | 'MANAGEMENT' | 'CUSTOM'
  parent_group_id: number | null
  tenant_id: number | null
  description: string | null
  permissions: Record<string, boolean>
  is_system: boolean
  is_active: boolean
  member_count: number
  members?: GroupMember[]
}

/** A row in Owner / Release Manager user management. */
export interface ManagedUser {
  id: number
  full_name: string
  username: string
  email: string
  role: 'TENANT_USER' | 'ADMIN'
  /** The single protected owner account; never a valid target for admin actions. */
  is_owner: boolean
  is_active: boolean
  must_change_password: boolean
  created_at: string
  groups?: Pick<AccessGroup, 'id' | 'name' | 'group_type' | 'tenant_id'>[]
}

/** The tenant master as an administrator sees it. */
export interface AdminTenant {
  id: number
  name: string
  tenant_code: string | null
  description: string | null
  weekly_booking_limit: number | null
  is_active: boolean
}

export interface AuthSession {
  access_token: string
  token_type: string
  expires_in: number
  user: AuthUser
}

export interface AuthUser {
  id: number
  full_name: string
  username: string
  email: string | null
  role: 'TENANT_USER' | 'ADMIN'
  /** Only the Owner may manage other Release Manager accounts. */
  is_owner?: boolean
  must_change_password?: boolean
  groups?: Pick<AccessGroup, 'id' | 'name' | 'group_type' | 'tenant_id'>[]
}

export interface AdminSettings {
  regular_slots_per_day: number
  weekly_booking_limit: number
  booking_freeze_dates: number
  jira_required_at_booking: boolean
  max_file_size_mb: number
}

export interface SlotConfig {
  id?: number
  slot_number: number
  name: string
  start_time: string
  end_time: string
  enabled: boolean
}

export interface AuditEvent {
  id: number
  booking_reference: string | null
  tenant_id?: number | null
  tenant_name?: string | null
  event_type: string
  actor_type: 'USER' | 'ADMIN' | 'SYSTEM'
  requester_email: string | null
  admin_username: string | null
  actor_access?: 'SCHEDULER' | 'TENANT_MEMBER' | 'COLLABORATOR' | null
  override_reason: string | null
  old_values: Record<string, unknown> | null
  new_values: Record<string, unknown> | null
  created_at: string
}

/** Everything the booking form collects. */
export interface BookingFormValues {
  tenant_id: string
  jira_number: string
  jira_url: string
  technology: string
  verifier_name: string
  verifier_email: string
  git_repository: string
  implementation_summary: string
  deployment_description: string
  additional_comments: string
  justification: string
  impacted_region: string
  emergency_reason: string
  emergency_approval_reference: string
  emergency_approver: string
  business_justification: string
  override_reason: string
}

export type FilterKey =
  | 'ALL'
  | 'AVAILABLE'
  | 'BOOKED'
  | 'MINE'
  | 'EMERGENCY'
  | 'LOCKED'
  | 'MISSING_DOCS'
  | `TECH:${string}`

export interface BookingComment {
  images?: CommentImage[]
  attachments?: { id: string; original_filename: string; size_bytes: number }[]
  id: number
  body: string
  internal: boolean
  author_name: string
  author_id: number
  created_at: string
}

export interface ScheduleSearchResult {
  id: number
  booking_reference: string
  tenant_name: string
  deployment_date: string
  status: BookingStatus
  change_number: string | null
}

export interface CommentImageRef {
  kind: 'document' | 'comment'
  attachment_id: string
  comment_id?: number | null
}
export interface CommentImage extends CommentImageRef {
  original_filename: string
  internal: boolean
}

/** A tenant as offered by search, history and audit autocomplete. */
export interface TenantOption {
  id: number
  name: string
  tenant_code: string | null
  is_active: boolean
}

/** A schedule as listed in tenant search and history (lean; open for full detail). */
export interface ScheduleListItem {
  id: number
  booking_reference: string
  tenant_id: number
  tenant_name: string
  deployment_date: string
  slot_number: number | null
  is_emergency: boolean
  status: BookingStatus
  change_number: string | null
  jira_number: string | null
  jira_url: string | null
  release_managers: string[]
}

export interface UpcomingWeek {
  week_start: string
  week_end: string
  week_label: string
  schedules: ScheduleListItem[]
}

/** One tenant's upcoming schedules, grouped only into weeks that hold one. */
export interface TenantUpcoming {
  tenant_id: number
  tenant_name: string
  weeks: UpcomingWeek[]
  truncated: boolean
}

/** Days XOR From/To: choosing one clears the other, so the two never conflict. */
export interface DateWindowValue {
  days: number | null
  dateFrom: string
  dateTo: string
}
