import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { TeamsNotificationSettings } from '../types'
import { api } from '../services/api'
import { AdminPanel } from './AdminPanel'
import { ToastProvider } from './ToastNotification'

// Unlisted API calls resolve to an empty list.
vi.mock('../services/api', () => {
  const calls: Record<string, ReturnType<typeof vi.fn>> = {}
  return {
    api: new Proxy(calls, { get: (target, key: string) => (target[key] ??= vi.fn().mockResolvedValue([])) }),
    ApiError: class extends Error {},
  }
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

async function open(settings: TeamsNotificationSettings, isOwner: boolean) {
  vi.mocked(api.getTeamsNotifications).mockResolvedValue(settings)
  render(<ToastProvider><AdminPanel open onClose={vi.fn()} timezone="Asia/Kolkata" currentUserId={1} isOwner={isOwner} onChanged={vi.fn()} /></ToastProvider>)
  fireEvent.click(screen.getByRole('button', { name: /Notifications/ }))
  await screen.findByText(/Status:/)
}

it('warns when the saved webhook is an old connector URL that is never called', async () => {
  await open({ enabled: true, webhook_configured: true, webhook_valid: false }, true)
  expect(screen.getByRole('alert').textContent).toMatch(/not a Teams Workflows URL/)
  expect(screen.getByText(/Webhook needs replacing/)).toBeTruthy()
})

it('shows a valid Workflows webhook as configured without a warning', async () => {
  await open({ enabled: true, webhook_configured: true, webhook_valid: true }, true)
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.getByText(/Webhook configured · Notifications enabled/)).toBeTruthy()
})

it('lets Release Managers view the status but not change or test it', async () => {
  await open({ enabled: false, webhook_configured: true, webhook_valid: true }, false)
  expect((screen.getByLabelText(/Enable booking notifications/) as HTMLInputElement).disabled).toBe(true)
  expect(screen.queryByLabelText(/Teams webhook URL/)).toBeNull()
  expect(screen.queryByRole('button', { name: /Save Teams settings|Send test notification|Remove webhook/ })).toBeNull()
})
