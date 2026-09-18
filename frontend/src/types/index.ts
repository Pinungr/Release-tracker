/** Mirrors the FastAPI response schemas. Nothing here is hard-coded data. */

export type DocumentCategory =
  | 'TEST_RESULTS'
  | 'INVENTORY'
  | 'IMPLEMENTATION_PLAN'
  | 'VALIDATION_PLAN'
  | 'DBA_SCRIPT'
  | 'SUPPORTING_DOCUMENTS'

export type SlotState =
  | 'AVAILABLE'
  | 'BOOKED'
  | 'HOLIDAY'
  | 'DISABLED'
  | 'EMERGENCY_AVAILABLE'

export type BookingStatus =
  | 'BOOKED'
  | 'LOCKED'
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
}

export interface BookingSummary {
  id: number
  booking_reference: string
  tenant_name: string
  deployment_date: string
  slot_number: number
  jira_change: string
  jira_task: string | null
  jira_url: string | null
  technology: string
  environment: string
  verifier_name: string
  status: BookingStatus
  is_emergency: boolean
  is_locked: boolean
  lock_deadline: string | null
  documents: DocumentReadiness
  created_at: string
  updated_at: string
}

export interface BookingDetail extends BookingSummary {
  requester_name: string
  requester_email: string
  requester_phone: string | null
  verifier_email: string
  git_repository: string
  implementation_summary: string
  deployment_description: string
  additional_comments: string | null
  emergency_reason: string | null
  emergency_approval_reference: string | null
  emergency_approver: string | null
  business_justification: string | null
  cancelled_at: string | null
  created_by_admin: string | null
  attachments: Attachment[]
  can_edit: boolean
  slot_label: string
  slot_time: string
}

export interface BookingCreated {
  booking: BookingDetail
  manage_token: string
  manage_url: string
  message: string
}

export interface SlotView {
  slot_number: number
  name: string
  start_time: string
  end_time: string
  time_label: string
  is_emergency: boolean
  enabled: boolean
  unavailable_reason: string | null
  state: SlotState
  bookable_by_public: boolean
  bookable_by_admin: boolean
  booking: BookingSummary | null
}

export interface Holiday {
  id: number
  holiday_date: string
  name: string
  description: string | null
  is_full_day: boolean
  allow_emergency: boolean
}

export interface DailyOverride {
  id: number
  override_date: string
  regular_slots: number | null
  emergency_enabled: boolean | null
  note: string | null
}

export interface DayView {
  day: string
  weekday: string
  date_label: string
  is_today: boolean
  is_past: boolean
  holiday: Holiday | null
  override: DailyOverride | null
  regular_slots_total: number
  regular_slots_used: number
  slots: SlotView[]
}

export interface ScheduleSummary {
  regular_slots_total: number
  regular_slots_available: number
  slots_booked: number
  holidays: number
  emergency_slots_total: number
  emergency_slots_booked: number
}

export interface DocumentCatalogEntry {
  category: DocumentCategory
  label: string
  required: boolean
  multiple: boolean
}

export interface PublicSettings {
  weekly_booking_limit: number
  booking_freeze_hours: number
  max_file_size_mb: number
  mandatory_documents: DocumentCategory[]
  document_catalog: DocumentCatalogEntry[]
  technologies: string[]
}

export interface Schedule {
  week_start: string
  week_end: string
  week_label: string
  today: string
  timezone: string
  days: DayView[]
  summary: ScheduleSummary
  settings: PublicSettings
}

export interface OwnerCredentials {
  requester_email: string
  booking_pin: string
}

export interface AdminSession {
  access_token: string
  token_type: string
  expires_in: number
  username: string
  display_name: string
}

export interface AdminSettings {
  regular_slots_per_day: number
  weekly_booking_limit: number
  booking_freeze_hours: number
  max_file_size_mb: number
  emergency_slot_enabled: boolean
  require_admin_override_reason: boolean
  mandatory_documents: DocumentCategory[]
}

export interface SlotConfig {
  id?: number
  slot_number: number
  name: string
  start_time: string
  end_time: string
  is_emergency: boolean
  enabled: boolean
}

export interface AuditEvent {
  id: number
  booking_reference: string | null
  event_type: string
  actor_type: 'PUBLIC' | 'ADMIN' | 'SYSTEM'
  requester_email: string | null
  admin_username: string | null
  override_reason: string | null
  old_values: Record<string, unknown> | null
  new_values: Record<string, unknown> | null
  created_at: string
}

/** Everything the booking form collects. */
export interface BookingFormValues {
  tenant_name: string
  jira_change: string
  jira_task: string
  jira_url: string
  environment: string
  technology: string
  requester_name: string
  requester_email: string
  requester_phone: string
  verifier_name: string
  verifier_email: string
  git_repository: string
  implementation_summary: string
  deployment_description: string
  additional_comments: string
  booking_pin: string
  confirm_booking_pin: string
  emergency_reason: string
  emergency_approval_reference: string
  emergency_approver: string
  business_justification: string
  override_weekly_limit: boolean
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
