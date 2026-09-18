import type { BookingDetail, BookingFormValues, PublicSettings, Tenant } from '../types'
import { CheckboxField, FormSection, SelectField, TextArea, TextField } from './FormControls'

export const EMPTY_BOOKING_VALUES: BookingFormValues = {
  tenant_id: '',
  jira_change: '',
  jira_task: '',
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
    jira_change: booking.jira_change,
    jira_task: booking.jira_task ?? '',
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
    'jira_change',
    'technology',
    'environment',
    'requester_name',
    'requester_email',
    'verifier_name',
    'verifier_email',
    'git_repository',
    'implementation_summary',
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
    jira_change: values.jira_change.trim(),
    jira_task: optional(values.jira_task),
    jira_url: optional(values.jira_url),
    environment: values.environment.trim() || 'PROD',
    technology: values.technology,
    requester_name: values.requester_name.trim(),
    requester_email: values.requester_email.trim(),
    requester_phone: optional(values.requester_phone),
    verifier_name: values.verifier_name.trim(),
    verifier_email: values.verifier_email.trim(),
    git_repository: values.git_repository.trim(),
    implementation_summary: values.implementation_summary.trim(),
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
  isAdmin: boolean
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
  isAdmin,
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
          label="JIRA change number"
          name="jira_change"
          required
          value={values.jira_change}
          onChange={(v) => onChange('jira_change', v)}
          error={errors.jira_change}
          placeholder="CHG0920798"
          maxLength={64}
        />
        <TextField
          label="JIRA task number"
          name="jira_task"
          value={values.jira_task}
          onChange={(v) => onChange('jira_task', v)}
          error={errors.jira_task}
          placeholder="CTASK3388771"
          hint="Optional."
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
          hint="Optional. When present, the JIRA number becomes a link on the board."
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
          required
          value={values.requester_email}
          onChange={(v) => onChange('requester_email', v)}
          error={errors.requester_email}
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
          required
          value={values.verifier_email}
          onChange={(v) => onChange('verifier_email', v)}
          error={errors.verifier_email}
        />
      </FormSection>

      <FormSection title="Deployment detail">
        <TextArea
          label="Implementation summary"
          name="implementation_summary"
          required
          value={values.implementation_summary}
          onChange={(v) => onChange('implementation_summary', v)}
          error={errors.implementation_summary}
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

      {isAdmin ? (
        <FormSection
          title="Administrator options"
          description="Overrides are recorded in the audit history with the reason you give."
        >
          <div className="sm:col-span-2">
            <CheckboxField
              label="Override the weekly booking limit for this tenant"
              name="override_weekly_limit"
              checked={values.override_weekly_limit}
              onChange={(v) => onChange('override_weekly_limit', v)}
              hint={`The limit is ${settings.weekly_booking_limit} regular deployments per tenant, per week.`}
            />
          </div>
          <TextField
            label="Override reason"
            name="override_reason"
            value={values.override_reason}
            onChange={(v) => onChange('override_reason', v)}
            error={errors.override_reason}
            placeholder="Critical business deployment."
            hint="Required when you override a rule such as the weekly limit or the freeze window."
            className="sm:col-span-2"
            maxLength={500}
          />
        </FormSection>
      ) : null}
    </form>
  )
}
