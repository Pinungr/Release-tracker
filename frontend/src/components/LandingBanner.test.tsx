import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { NextAvailableSlot, Schedule } from '../types'
import { LandingBanner } from './LandingBanner'

afterEach(cleanup)

const next: NextAvailableSlot = {
  deployment_date: '2026-10-06',
  week_start: '2026-10-04',
  weekday: 'Tuesday',
  date_label: '06 Oct 2026',
  slot_number: 2,
  slot_name: 'Slot 2',
  time_label: '09:00 PM - 05:00 AM',
}

function schedule(overrides: Partial<Schedule>): Schedule {
  return { week_start: '2026-09-27', ...overrides } as Schedule
}

it('offers a jump when the next free slot is in a later week', () => {
  const onGoToWeek = vi.fn()
  render(
    <LandingBanner
      schedule={schedule({ landing_message: 'No free slot this week. Next available slot: …', next_available: next })}
      onGoToWeek={onGoToWeek}
    />,
  )
  expect(screen.getByRole('status').textContent).toContain('No free slot this week')
  fireEvent.click(screen.getByRole('button', { name: /Go to Tue 06 Oct 2026/ }))
  expect(onGoToWeek).toHaveBeenCalledWith('2026-10-04')
})

it('shows no jump when the free slot is already on the board', () => {
  render(
    <LandingBanner
      schedule={schedule({
        week_start: '2026-10-04',
        landing_message: 'Next available slot: Tue 06 Oct 2026 · Slot 2.',
        next_available: next,
      })}
      onGoToWeek={vi.fn()}
    />,
  )
  expect(screen.getByRole('status').textContent).toContain('Next available slot')
  expect(screen.queryByRole('button')).toBeNull()
})

it('still explains when nothing is free at all', () => {
  render(
    <LandingBanner
      schedule={schedule({ landing_message: 'No bookable slots in the next 60 days.', next_available: null })}
      onGoToWeek={vi.fn()}
    />,
  )
  expect(screen.getByRole('status').textContent).toContain('No bookable slots')
  expect(screen.queryByRole('button')).toBeNull()
})

it('renders nothing on an ordinary week view', () => {
  const { container } = render(<LandingBanner schedule={schedule({})} onGoToWeek={vi.fn()} />)
  expect(container.innerHTML).toBe('')
})
