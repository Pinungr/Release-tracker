import type { BookingDetail, BookingFormValues, DocumentCategory, PublicSettings, Tenant } from '../types'
import { FormSection, SelectField, TextArea, TextField } from './FormControls'

const DOCUMENT_ACCEPT = '.pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.zip,.sql,.png,.jpg,.jpeg'

export type BookingDocumentFiles = Partial<Record<DocumentCategory, File[]>>
export type BookingDocumentErrors = Partial<Record<DocumentCategory, string>>

export const EMPTY_BOOKING_VALUES: BookingFormValues = {
  tenant_id: '',
  jira_number: '',
  jira_url: '',
  environment: 'PROD',
  technology: 'Databricks',
  requester_name: '',
  requester_email: '',
  requester_phone: '',
  verifier_name: '',
  verifier_email: '',
  git_repository: '',
  implementation_summary: '',
  deployment_description: '',
  additional_comments: '',
  emergency_reason: '',
  emergency_approval_reference: '',
  emergency_approver: '',
  business_justification: '',
  override_weekly_limit: false,
  override_reason: '',
}

export function valuesFromBooking(booking: BookingDetail): BookingFormValues {
  return {
    ...EMPTY_BOOKING_VALUES,
    tenant_id: String(booking.tenant_id),
    jira_number: booking.jira_number,
    jira_url: booking.jira_url ?? '',
    environment: booking.environment,
    technology: booking.technology,
    requester_name: booking.requester_name,
    requester_email: booking.requester_email,
    requester_phone: booking.requester_phone ?? '',
    verifier_name: booking.verifier_name,
    verifier_email: booking.verifier_email,
    git_repository: booking.git_repository,
    implementation_summary: booking.implementation_summary,
    deployment_description: booking.deployment_description,
    additional_comments: booking.additional_comments ?? '',
    emergency_reason: booking.emergency_reason ?? '',
    emergency_approval_reference: booking.emergency_approval_reference ?? '',
    emergency_approver: booking.emergency_approver ?? '',
    business_justification: booking.business_justification ?? '',
  }
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/
const HTTP_URL = /^https?:\/\/[^\s/$.?#].[^\s]*$/i
const GIT_URL = /^(git|ssh):\/\/\S+$|^[\w.-]+@[\w.-]+:[\w./~-]+$/i

export type BookingFormErrors = Partial<Record<keyof BookingFormValues, string>>

/**
 * Frontend validation is purely for fast feedback — the API re-validates
 * every one of these rules and is the source of truth.
 */
export function validateBookingForm(
  values: BookingFormValues,
  options: { isEmergency: boolean },
): BookingFormErrors {
  const errors: BookingFormErrors = {}
  const required: (keyof BookingFormValues)[] = [
    'tenant_id',
    'jira_number',
    'technology',
    'environment',
    'requester_name',
    'verifier_name',
    'git_repository',
    'deployment_description',
  ]
  for (const field of required) {
    if (!String(values[field] ?? '').trim()) errors[field] = 'This field is required.'
  }

  if (values.requester_email && !EMAIL.test(values.requester_email)) {
    errors.requester_email = 'Enter a valid email address.'
  }
  if (values.verifier_email && !EMAIL.test(values.verifier_email)) {
    errors.verifier_email = 'Enter a valid email address.'
  }
  if (values.git_repository && !HTTP_URL.test(values.git_repository) && !GIT_URL.test(values.git_repository)) {
    errors.git_repository = 'Enter a valid Git URL (https://…, ssh://… or git@host:path).'
  }
  if (values.jira_url.trim() && !HTTP_URL.test(values.jira_url.trim())) {
    errors.jira_url = 'Enter a valid http(s) URL, or leave it blank.'
  }
  if (values.implementation_summary.trim() && values.implementation_summary.trim().length < 10) {
    errors.implementation_summary = 'Add at least 10 characters.'
  }
  if (values.deployment_description.trim() && values.deployment_description.trim().length < 10) {
    errors.deployment_description = 'Add at least 10 characters.'
  }

  if (options.isEmergency) {
    if (!values.emergency_reason.trim()) errors.emergency_reason = 'This field is required.'
    if (!values.business_justification.trim()) {
      errors.business_justification = 'This field is required.'
    }
  }

  return errors
}

/** Strips empty optional strings so the API receives nulls, not blanks. */
export function toBookingPayload(
  values: BookingFormValues,
  extra: Record<string, unknown>,
): Record<string, unknown> {
  const optional = (value: string) => (value.trim() ? value.trim() : null)
  return {
    tenant_id: values.tenant_id ? Number(values.tenant_id) : null,
    jira_number: values.jira_number.trim(),
    jira_url: optional(values.jira_url),
    environment: values.environment.trim() || 'PROD',
    technology: values.technology,
    requester_name: values.requester_name.trim(),
    requester_email: optional(values.requester_email),
    requester_phone: optional(values.requester_phone),
    verifier_name: values.verifier_name.trim(),
    verifier_email: optional(values.verifier_email),
    git_repository: values.git_repository.trim(),
    implementation_summary: optional(values.implementation_summary),
    deployment_description: values.deployment_description.trim(),
    additional_comments: optional(values.additional_comments),
    emergency_reason: optional(values.emergency_reason),
    emergency_approval_reference: optional(values.emergency_approval_reference),
    emergency_approver: optional(values.emergency_approver),
    business_justification: optional(values.business_justification),
    ...extra,
  }
}

interface BookingFormProps {
  formId: string
  values: BookingFormValues
  tenants: Tenant[]
  errors: BookingFormErrors
  settings: PublicSettings
  isEmergency: boolean
  showDocumentUpload?: boolean
  documents?: BookingDocumentFiles
  documentErrors?: BookingDocumentErrors
  onDocumentsChange?: (category: DocumentCategory, files: File[]) => void
  onChange: <K extends keyof BookingFormValues>(field: K, value: BookingFormValues[K]) => void
  onSubmit: () => void
}

export function BookingForm({
  formId,
  values,
  tenants,
  errors,
  settings,
  isEmergency,
  showDocumentUpload = false,
  documents = {},
  documentErrors = {},
  onDocumentsChange,
  onChange,
  onSubmit,
}: BookingFormProps) {
  const technologies = settings.technologies.map((tech) => ({ value: tech, label: tech }))

  return (
    <form
      id={formId}
      noValidate
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit()
      }}
      className="space-y-6"
    >
      <FormSection title="Change record" description="Identifies the deployment in your change system.">
        <SelectField
          label="Tenant name"
          name="tenant_id"
          required
          value={values.tenant_id}
          onChange={(v) => onChange('tenant_id', v)}
          options={tenants.map((tenant) => ({ value: String(tenant.id), label: tenant.name }))}
          placeholder="Select tenant"
          error={errors.tenant_id}
        />
        <SelectField
          label="Deployment technology"
          name="technology"
          required
          value={values.technology}
          onChange={(v) => onChange('technology', v)}
          options={technologies}
          error={errors.technology}
        />
        <TextField
          label="Jira No."
          name="jira_number"
          required
          value={values.jira_number}
          onChange={(v) => onChange('jira_number', v)}
          error={errors.jira_number}
          placeholder="JIRA-12345"
          maxLength={64}
        />
        <TextField
          label="JIRA URL"
          name="jira_url"
          type="url"
          value={values.jira_url}
          onChange={(v) => onChange('jira_url', v)}
          error={errors.jira_url}
          placeholder="https://jira.example.com/browse/CHG0920798"
          hint="Optional URL for the Jira record. The Jira No. itself is required."
          className="sm:col-span-2"
        />
        <TextField
          label="Deployment environment"
          name="environment"
          required
          value={values.environment}
          onChange={(v) => onChange('environment', v)}
          error={errors.environment}
          maxLength={32}
        />
        <TextField
          label="Git repository URL"
          name="git_repository"
          required
          value={values.git_repository}
          onChange={(v) => onChange('git_repository', v)}
          error={errors.git_repository}
          placeholder="https://github.example.com/team/repo"
        />
      </FormSection>

      <FormSection title="People" description="Who is requesting the change and who verifies it.">
        <TextField
          label="Requester name"
          name="requester_name"
          required
          value={values.requester_name}
          onChange={(v) => onChange('requester_name', v)}
          error={errors.requester_name}
          autoComplete="name"
        />
        <TextField
          label="Requester email"
          name="requester_email"
          type="email"
          value={values.requester_email}
          onChange={(v) => onChange('requester_email', v)}
          error={errors.requester_email}
          hint="Optional."
          autoComplete="email"
        />
        <TextField
          label="Requester phone"
          name="requester_phone"
          type="tel"
          value={values.requester_phone}
          onChange={(v) => onChange('requester_phone', v)}
          error={errors.requester_phone}
          hint="Optional."
          autoComplete="tel"
        />
        <TextField
          label="Verifier name"
          name="verifier_name"
          required
          value={values.verifier_name}
          onChange={(v) => onChange('verifier_name', v)}
          error={errors.verifier_name}
        />
        <TextField
          label="Verifier email"
          name="verifier_email"
          type="email"
          value={values.verifier_email}
          onChange={(v) => onChange('verifier_email', v)}
          error={errors.verifier_email}
          hint="Optional."
        />
      </FormSection>

      <FormSection title="Deployment detail">
        <TextArea
          label="Implementation summary"
          name="implementation_summary"
          value={values.implementation_summary}
          onChange={(v) => onChange('implementation_summary', v)}
          error={errors.implementation_summary}
          hint="Optional."
          placeholder="What will be deployed, in one or two lines."
          className="sm:col-span-2"
          maxLength={4000}
        />
        <TextArea
          label="Deployment description"
          name="deployment_description"
          required
          rows={4}
          value={values.deployment_description}
          onChange={(v) => onChange('deployment_description', v)}
          error={errors.deployment_description}
          placeholder="Steps, components affected, dependencies and rollback approach."
          className="sm:col-span-2"
          maxLength={4000}
        />
        <TextArea
          label="Additional comments"
          name="additional_comments"
          value={values.additional_comments}
          onChange={(v) => onChange('additional_comments', v)}
          error={errors.additional_comments}
          hint="Optional."
          className="sm:col-span-2"
          maxLength={4000}
        />
      </FormSection>

      {showDocumentUpload ? (
        <section className="border-t border-line pt-5">
          <h3 className="text-sm font-semibold text-ink">Deployment documents</h3>
          <p className="mt-0.5 mb-3 text-xs text-ink-muted">
            Upload every document marked Required before the slot can be booked. Supporting documents can be added now or later.
          </p>
          <div className="space-y-3">
            {settings.document_catalog.map((entry) => {
              const selected = documents[entry.category] ?? []
              const error = documentErrors[entry.category]
              return (
                <div
                  key={entry.category}
                  className={`rounded-lg border p-3 ${
                    error ? 'border-rose-300 bg-rose-50/40' : 'border-line bg-surface'
                  }`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-ink">{entry.label}</span>
                    <span
                      className={`badge ${
                        entry.required ? 'bg-brand-50 text-brand-700' : 'bg-slate-100 text-slate-500'
                      }`}
                    >
                      {entry.required ? 'Required' : 'Optional'}
                    </span>
                    {entry.multiple ? (
                      <span className="text-xs text-ink-muted">Multiple files allowed</span>
                    ) : null}
                  </div>
                  <input
                    type="file"
                    accept={DOCUMENT_ACCEPT}
                    multiple={entry.multiple}
                    className={`mt-2 block w-full text-sm text-ink-muted file:mr-3 file:rounded-md file:border-0 file:bg-brand-50 file:px-3 file:py-2 file:text-sm file:font-medium file:text-brand-700 hover:file:bg-brand-100 ${
                      error ? 'rounded-md ring-1 ring-rose-300' : ''
                    }`}
                    onChange={(event) => {
                      const files = Array.from(event.target.files ?? [])
                      onDocumentsChange?.(entry.category, files)
                      event.target.value = ''
                    }}
                  />
                  {selected.length > 0 ? (
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <div className="min-w-0 flex-1 text-xs text-ink-muted">
                        {selected.map((file) => file.name).join(', ')}
                      </div>
                      <button
                        type="button"
                        className="btn-ghost btn-sm"
                        onClick={() => onDocumentsChange?.(entry.category, [])}
                      >
                        Clear
                      </button>
                    </div>
                  ) : null}
                  {error ? <p className="mt-1 text-xs font-medium text-rose-600">{error}</p> : null}
                </div>
              )
            })}
          </div>
          <p className="mt-3 text-xs text-ink-muted">
            Maximum file size: {settings.max_file_size_mb} MB per file.
          </p>
        </section>
      ) : null}

      {isEmergency ? (
        <FormSection
          title="Emergency change"
          description="Recorded against the emergency slot and visible in the audit history."
        >
          <TextArea
            label="Emergency reason"
            name="emergency_reason"
            required
            value={values.emergency_reason}
            onChange={(v) => onChange('emergency_reason', v)}
            error={errors.emergency_reason}
            className="sm:col-span-2"
            maxLength={2000}
          />
          <TextArea
            label="Business justification"
            name="business_justification"
            required
            value={values.business_justification}
            onChange={(v) => onChange('business_justification', v)}
            error={errors.business_justification}
            className="sm:col-span-2"
            maxLength={2000}
          />
          <TextField
            label="Emergency approver"
            name="emergency_approver"
            value={values.emergency_approver}
            onChange={(v) => onChange('emergency_approver', v)}
            error={errors.emergency_approver}
            hint="Optional."
            maxLength={120}
          />
          <TextField
            label="Emergency approval reference"
            name="emergency_approval_reference"
            value={values.emergency_approval_reference}
            onChange={(v) => onChange('emergency_approval_reference', v)}
            error={errors.emergency_approval_reference}
            hint="Optional."
            maxLength={120}
          />
        </FormSection>
      ) : null}

    </form>
  )
}
