/**
 * Date helpers.
 *
 * All schedule dates travel as plain `YYYY-MM-DD` strings. They are parsed at
 * UTC noon so a browser in any timezone can never shift the calendar day, and
 * they are formatted in the Indian style the sheet this replaces used.
 */

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function parseIsoDate(value: string): Date {
  const [year, month, day] = value.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, day, 12))
}

export function toIsoDate(date: Date): string {
  return [
    date.getUTCFullYear(),
    String(date.getUTCMonth() + 1).padStart(2, '0'),
    String(date.getUTCDate()).padStart(2, '0'),
  ].join('-')
}

export function addDays(iso: string, days: number): string {
  const date = parseIsoDate(iso)
  date.setUTCDate(date.getUTCDate() + days)
  return toIsoDate(date)
}

/** Sunday of the deployment week containing `iso`. */
export function weekStart(iso: string): string {
  const date = parseIsoDate(iso)
  return addDays(iso, -date.getUTCDay())
}

/** `17 Sep 2026` */
export function formatDate(iso: string): string {
  const date = parseIsoDate(iso)
  return `${String(date.getUTCDate()).padStart(2, '0')} ${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}`
}

const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

/** `Tuesday` */
export function weekdayOf(iso: string): string {
  return WEEKDAYS[parseIsoDate(iso).getUTCDay()]!
}

/** `10:30 AM` from a `HH:MM:SS` slot time. */
export function formatSlotTime(value: string): string {
  const [hoursRaw, minutes] = value.split(':')
  const hours = Number(hoursRaw)
  const suffix = hours >= 12 ? 'PM' : 'AM'
  const display = hours % 12 === 0 ? 12 : hours % 12
  return `${String(display).padStart(2, '0')}:${minutes} ${suffix}`
}

/** `17 Sep 2026, 10:30 AM` in the scheduler's own timezone. */
export function formatTimestamp(utcIso: string | null, timeZone: string): string {
  if (!utcIso) return '—'
  // The API sends naive UTC; mark it explicitly so the browser converts once.
  const stamp = utcIso.endsWith('Z') || /[+-]\d\d:\d\d$/.test(utcIso) ? utcIso : `${utcIso}Z`
  const date = new Date(stamp)
  if (Number.isNaN(date.getTime())) return '—'
  const parts = new Intl.DateTimeFormat('en-IN', {
    timeZone,
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  }).format(date)
  return parts.replace(/,\s*(\d)/, ', $1')
}

/** Human countdown used on the lock tooltip, e.g. `in 2 days` / `6 hours ago`. */
export function relativeToNow(utcIso: string | null): string {
  if (!utcIso) return ''
  const stamp = utcIso.endsWith('Z') ? utcIso : `${utcIso}Z`
  const diffMs = new Date(stamp).getTime() - Date.now()
  if (Number.isNaN(diffMs)) return ''
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ['day', 86_400_000],
    ['hour', 3_600_000],
    ['minute', 60_000],
  ]
  const formatter = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })
  for (const [unit, ms] of units) {
    if (Math.abs(diffMs) >= ms || unit === 'minute') {
      return formatter.format(Math.round(diffMs / ms), unit)
    }
  }
  return ''
}
