import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { AdminGroupManager } from './AdminGroupManager'
import { ToastProvider } from './ToastNotification'
import { api } from '../services/api'
import type { AccessGroup, GroupMember, ManagedUser } from '../types'

vi.mock('../services/api', () => ({
  api: {
    listGroups: vi.fn(),
    getGroup: vi.fn(),
    listUsers: vi.fn(),
    createGroup: vi.fn(),
    addGroupMember: vi.fn(),
    removeGroupMember: vi.fn(),
    deleteGroup: vi.fn(),
  },
  ApiError: class extends Error {},
}))
const member: GroupMember = {
  id: 20,
  full_name: 'Tusar Das',
  username: 'tusar',
  email: 'tusar@example.com',
  is_active: true,
  is_owner: false,
}
const candidate: ManagedUser = {
  id: 21,
  full_name: 'Adrian Roy',
  username: 'adrian',
  email: 'adrian@example.com',
  is_active: true,
  is_owner: false,
  role: 'TENANT_USER',
  must_change_password: false,
  created_at: '',
}
function group(
  id: number,
  name: string,
  group_type: AccessGroup['group_type'],
  parent_group_id: number | null = null,
): AccessGroup {
  return {
    id,
    name,
    group_type,
    parent_group_id,
    tenant_id: null,
    description: null,
    permissions: {},
    is_system: group_type !== 'CUSTOM',
    is_active: true,
    member_count: 0,
    members: [],
  }
}
const groups = [
  group(1, 'Member Pool', 'MEMBER_POOL'),
  group(2, 'Release Managers', 'RELEASE_MANAGERS'),
  group(3, 'Tenants', 'TENANTS'),
  group(4, 'Management', 'MANAGEMENT'),
  { ...group(5, 'Rada', 'TENANT_SUBGROUP', 3), member_count: 1, members: [member] },
  group(6, 'DBA', 'CUSTOM'),
]
const view = (route: string, isOwner = true) => (
  <ToastProvider>
    <AdminGroupManager route={route} isOwner={isOwner} />
  </ToastProvider>
)
beforeEach(() => {
  vi.resetAllMocks()
  vi.stubGlobal('scrollTo', vi.fn())
  vi.mocked(api.listGroups).mockResolvedValue(groups)
  vi.mocked(api.getGroup).mockImplementation(async (id) => groups.find((g) => g.id === id)!)
  vi.mocked(api.listUsers).mockResolvedValue([candidate])
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('opens a tenant directly from its URL and exposes distinct group links', async () => {
  render(view('#/admin/groups/tenants/rada'))
  await screen.findByRole('heading', { name: 'Rada', level: 1 })
  expect(await screen.findByText('Tusar Das')).toBeTruthy()
  const nav = screen.getByRole('navigation', { name: 'Group navigation' })
  expect(
    within(nav)
      .getByRole('link', { name: /Release Managers/ })
      .getAttribute('href'),
  ).toBe('#/admin/groups/Release%20Managers')
  expect(within(nav).getByRole('link', { name: /Rada/ }).getAttribute('aria-current')).toBe('page')
})

it('shows a recoverable not-found page for a deleted or invalid group', async () => {
  render(view('#/admin/groups/999'))
  await screen.findByRole('heading', { name: 'Group not found' })
  expect(api.getGroup).not.toHaveBeenCalled()
  expect(screen.getByRole('link', { name: 'View all groups' }).getAttribute('href')).toBe('#/admin/groups')
})

it('preserves owner-only Release Manager membership controls', async () => {
  render(view('#/admin/groups/2', false))
  await screen.findByText(/Only the organization owner/)
  expect(screen.queryByRole('button', { name: 'Add members' })).toBeNull()
  expect(screen.queryByRole('button', { name: /Remove / })).toBeNull()
})

it('displays tenant subgroup pages instead of editable automatic membership', async () => {
  render(view('#/admin/groups/3'))
  const section = await screen.findByRole('region', { name: 'Tenant groups' })
  expect(within(section).getByRole('link', { name: /Rada/ }).getAttribute('href')).toBe('#/admin/groups/tenants/rada')
  expect(screen.queryByRole('button', { name: 'Add members' })).toBeNull()
})

it('excludes existing members even when the member table is filtered', async () => {
  vi.mocked(api.listUsers).mockResolvedValue([
    { ...candidate, ...member },
    candidate,
    { ...candidate, id: 22, is_owner: true },
    { ...candidate, id: 23, is_active: false },
  ])
  vi.mocked(api.addGroupMember).mockResolvedValue({
    ...groups[4],
    members: [member, candidate],
    member_count: 2,
  })
  render(view('#/admin/groups/5'))
  await screen.findByText('Tusar Das')
  fireEvent.change(screen.getByRole('textbox', { name: 'Search members' }), { target: { value: 'nobody' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add members' }))
  const dialog = await screen.findByRole('dialog', { name: 'Add members to Rada' })
  const add = await within(dialog).findByRole('button', { name: 'Add Adrian Roy' })
  expect(within(dialog).queryByRole('button', { name: 'Add Tusar Das' })).toBeNull()
  expect(within(dialog).getAllByRole('button', { name: /^Add / })).toHaveLength(1)
  fireEvent.click(add)
  await waitFor(() => expect(api.addGroupMember).toHaveBeenCalledWith(5, 21))
  await within(dialog).findByText('1 member added')
  expect(within(dialog).queryByRole('button', { name: 'Add Adrian Roy' })).toBeNull()
})

it('requires confirmation before removing a member', async () => {
  vi.mocked(api.removeGroupMember).mockResolvedValue({ ...groups[4], members: [], member_count: 0 })
  render(view('#/admin/groups/5'))
  fireEvent.click(await screen.findByRole('button', { name: 'Remove Tusar Das' }))
  expect(api.removeGroupMember).not.toHaveBeenCalled()
  fireEvent.click(
    within(screen.getByRole('dialog', { name: 'Remove member?' })).getByRole('button', {
      name: 'Remove member',
    }),
  )
  await waitFor(() => expect(api.removeGroupMember).toHaveBeenCalledWith(5, 20))
  await screen.findByText('No members yet')
})

it('does not show members from a slow previous group after navigation', async () => {
  let resolveOld!: (value: AccessGroup) => void
  vi.mocked(api.getGroup).mockImplementation((id) =>
    id === 5
      ? new Promise((resolve) => {
          resolveOld = resolve
        })
      : Promise.resolve(groups[1]),
  )
  const rendered = render(view('#/admin/groups/5'))
  await waitFor(() => expect(api.getGroup).toHaveBeenCalledWith(5))
  rendered.rerender(view('#/admin/groups/2'))
  await screen.findByRole('heading', { name: 'Release Managers', level: 1 })
  await act(async () => resolveOld(groups[4]))
  expect(screen.queryByText('Tusar Das')).toBeNull()
})

it('offers retry when loading the directory fails', async () => {
  vi.mocked(api.listGroups).mockRejectedValueOnce(new Error('Offline'))
  render(view('#/admin/groups'))
  await screen.findByRole('alert')
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  await screen.findByRole('heading', { name: 'Group directory' })
})


it('opens a named Release Manager page without changing its owner-only permissions', async () => {
  render(view('#/admin/groups/Release%20Managers', false))
  await screen.findByRole('heading', { name: 'Release Managers', level: 1 })
  await screen.findByText(/Only the organization owner/)
  expect(api.getGroup).toHaveBeenCalledWith(2)
  expect(screen.queryByRole('button', { name: 'Add members' })).toBeNull()
})

it('uses named URLs in the mobile selector and tenant breadcrumb', async () => {
  render(view('#/admin/groups/tenants/rada'))
  await screen.findByRole('heading', { name: 'Rada', level: 1 })
  const breadcrumb = screen.getByRole('navigation', { name: 'Breadcrumb' })
  expect(within(breadcrumb).getByRole('link', { name: 'Tenants' }).getAttribute('href')).toBe('#/admin/groups/Tenants')
  fireEvent.change(screen.getByLabelText('Navigate groups'), { target: { value: '2' } })
  expect(window.location.hash).toBe('#/admin/groups/Release%20Managers')
})
