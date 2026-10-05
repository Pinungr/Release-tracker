import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { api } from '../services/api'
import type { AIAssistantAccess } from '../types'
import { PDSAIChat } from './PDSAIChat'

vi.mock('../services/api', () => ({
  api: { getAIAssistantAccess: vi.fn(), chatPDSAI: vi.fn() },
  ApiError: class extends Error {},
}))

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn()
  vi.mocked(api.getAIAssistantAccess).mockResolvedValue({
    allowed: true,
    chat_configured: true,
    provider: 'builtin',
    provider_label: 'Built-in',
  } as AIAssistantAccess)
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

async function ask(question: string) {
  fireEvent.click(await screen.findByRole('button', { name: 'Ask PDS' }))
  fireEvent.change(screen.getByLabelText('Ask PDS'), { target: { value: question } })
  fireEvent.keyDown(screen.getByLabelText('Ask PDS'), { key: 'Enter' })
}

it('offers a slot booking link and opens the selected booking form', async () => {
  vi.mocked(api.chatPDSAI).mockResolvedValue({
    answer: 'The next available deployment slot is Tuesday, October 6, 2026.',
    model: 'PDS scheduling API',
    read_only: true,
    navigation: [{ kind: 'book_slot', date: '2026-10-06', slot_number: 2 }],
  })
  const onBookSlot = vi.fn()
  render(<PDSAIChat onBookSlot={onBookSlot} />)
  await ask('When is the next available slot?')

  const link = await screen.findByRole('link', { name: 'Book this slot' })
  expect(link.getAttribute('href')).toBe('#/dashboard?date=2026-10-06&slot=2')
  fireEvent.click(link)
  expect(onBookSlot).toHaveBeenCalledWith('2026-10-06', 2)
})

it('offers a direct link for a verified PDS number', async () => {
  vi.mocked(api.chatPDSAI).mockResolvedValue({
    answer: 'PDS-001 is booked.',
    model: 'PDS backend API',
    read_only: true,
    navigation: [{ kind: 'schedule', reference: 'pds-001' }],
  })
  render(<PDSAIChat onBookSlot={vi.fn()} />)
  await ask('Show PDS-001')

  const link = await screen.findByRole('link', { name: 'Open PDS-001' })
  expect(link.getAttribute('href')).toBe('#/schedules/pds-001')
})
