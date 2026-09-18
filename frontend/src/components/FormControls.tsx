import type { ReactNode } from 'react'

interface BaseProps {
  label: string
  name: string
  required?: boolean
  hint?: string
  error?: string
  className?: string
}

function Wrapper({
  label,
  name,
  required,
  hint,
  error,
  className = '',
  children,
}: BaseProps & { children: ReactNode }) {
  return (
    <div className={className}>
      <label htmlFor={name} className="field-label">
        {label}
        {required ? <span className="ml-0.5 text-rose-500">*</span> : null}
      </label>
      {children}
      {error ? (
        <p id={`${name}-error`} className="mt-1 text-xs font-medium text-rose-600">
          {error}
        </p>
      ) : hint ? (
        <p className="mt-1 text-xs text-ink-muted">{hint}</p>
      ) : null}
    </div>
  )
}

interface TextFieldProps extends BaseProps {
  value: string
  onChange: (value: string) => void
  type?: 'text' | 'email' | 'tel' | 'url' | 'password' | 'date' | 'time' | 'number'
  placeholder?: string
  maxLength?: number
  inputMode?: 'text' | 'numeric' | 'email' | 'tel' | 'url'
  autoComplete?: string
  disabled?: boolean
  min?: number
  max?: number
}

export function TextField({
  value,
  onChange,
  type = 'text',
  placeholder,
  maxLength,
  inputMode,
  autoComplete,
  disabled,
  min,
  max,
  ...base
}: TextFieldProps) {
  return (
    <Wrapper {...base}>
      <input
        id={base.name}
        name={base.name}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        maxLength={maxLength}
        inputMode={inputMode}
        autoComplete={autoComplete}
        disabled={disabled}
        min={min}
        max={max}
        aria-invalid={base.error ? true : undefined}
        aria-describedby={base.error ? `${base.name}-error` : undefined}
        className={`field ${base.error ? 'field-error' : ''}`}
      />
    </Wrapper>
  )
}

interface TextAreaProps extends BaseProps {
  value: string
  onChange: (value: string) => void
  rows?: number
  placeholder?: string
  maxLength?: number
}

export function TextArea({
  value,
  onChange,
  rows = 3,
  placeholder,
  maxLength,
  ...base
}: TextAreaProps) {
  return (
    <Wrapper {...base}>
      <textarea
        id={base.name}
        name={base.name}
        value={value}
        rows={rows}
        placeholder={placeholder}
        maxLength={maxLength}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={base.error ? true : undefined}
        aria-describedby={base.error ? `${base.name}-error` : undefined}
        className={`field resize-y ${base.error ? 'field-error' : ''}`}
      />
    </Wrapper>
  )
}

interface SelectFieldProps extends BaseProps {
  value: string
  onChange: (value: string) => void
  options: { value: string; label: string }[]
  disabled?: boolean
  placeholder?: string
}

export function SelectField({ value, onChange, options, disabled, placeholder, ...base }: SelectFieldProps) {
  return (
    <Wrapper {...base}>
      <select
        id={base.name}
        name={base.name}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={base.error ? true : undefined}
        className={`field ${base.error ? 'field-error' : ''}`}
      >
        {placeholder ? (
          <option value="" disabled>
            {placeholder}
          </option>
        ) : null}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </Wrapper>
  )
}

export function CheckboxField({
  label,
  name,
  checked,
  onChange,
  hint,
}: {
  label: string
  name: string
  checked: boolean
  onChange: (checked: boolean) => void
  hint?: string
}) {
  return (
    <label htmlFor={name} className="flex cursor-pointer items-start gap-2.5">
      <input
        id={name}
        name={name}
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 size-4 rounded border-line text-brand-600 focus:ring-brand-500/30"
      />
      <span className="min-w-0">
        <span className="block text-sm font-medium text-ink">{label}</span>
        {hint ? <span className="block text-xs text-ink-muted">{hint}</span> : null}
      </span>
    </label>
  )
}

export function FormSection({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children: ReactNode
}) {
  return (
    <section className="border-t border-line pt-5 first:border-0 first:pt-0">
      <h3 className="text-sm font-semibold text-ink">{title}</h3>
      {description ? <p className="mt-0.5 mb-3 text-xs text-ink-muted">{description}</p> : <div className="mb-3" />}
      <div className="grid gap-4 sm:grid-cols-2">{children}</div>
    </section>
  )
}
