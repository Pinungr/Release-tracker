import type { ReactNode } from 'react'
import { Logout, Settings, Shield, User } from './Icons'

interface AppHeaderProps {
  groupsOpen?: boolean
  timezone: string
  username: string
  isAdmin: boolean
  isOwner: boolean
  onProfile: () => void
  onAdminPanel: () => void
  onLogout: () => void
  weekNavigator: ReactNode
}

export function AppHeader({
  groupsOpen = false,
  timezone,
  username,
  isAdmin,
  isOwner,
  onProfile,
  onAdminPanel,
  onLogout,
  weekNavigator,
}: AppHeaderProps) {
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-surface/90 backdrop-blur">
      <div className="mx-auto max-w-[88rem] px-4 sm:px-6 lg:px-8">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-3 py-3.5">
          {/* On phones the brand takes its own line so the title is never
              truncated down to a few characters. */}
          <a
            href="#"
            aria-label="Go to dashboard"
            title="Go to dashboard"
            className="flex min-w-0 flex-1 basis-full items-center gap-3 rounded-lg transition hover:opacity-80 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-brand-600 sm:basis-auto"
          >
            <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-brand-600 text-sm font-bold text-white shadow-sm">
              PD
            </span>
            <div className="min-w-0">
              <h1 className="truncate text-base leading-tight font-semibold text-ink sm:text-lg">
                Production Deployment Scheduler
              </h1>
              <p className="truncate text-xs text-ink-muted">
                {groupsOpen ? 'People & groups' : 'Weekly production release board'} · {timezone.replace('_', ' ')}
              </p>
            </div>
          </a>

          <div className="order-3 w-full lg:order-2 lg:w-auto">{weekNavigator}</div>

          <div className="order-2 ml-auto flex items-center gap-2 lg:order-3">
            <button type="button" onClick={onProfile} className="btn-secondary">
              <User className="size-4" />
              <span className="hidden sm:inline">{username}</span>
              <span className="sm:hidden">Profile</span>
            </button>

            {isAdmin ? (
              <>
                <a href={groupsOpen ? '#' : '#/admin/groups'} className="btn-secondary">{groupsOpen ? 'Schedule' : 'Groups'}</a>
                <span className="hidden items-center gap-1.5 rounded-lg bg-brand-50 px-2.5 py-1.5 text-xs font-semibold text-brand-700 sm:inline-flex">
                  <Shield className="size-4" />
                  {isOwner ? 'OWNER' : 'RELEASE MANAGER'}
                </span>
                <button type="button" onClick={onAdminPanel} className="btn-primary" aria-label="Release controls">
                  <Settings className="size-4" />
                  <span className="hidden sm:inline">Release controls</span>
                </button>
              </>
            ) : null}

            <button
              type="button"
              onClick={onLogout}
              className="btn-ghost px-2"
              aria-label="Sign out"
              title="Sign out"
            >
              <Logout className="size-4" />
            </button>
          </div>
        </div>
      </div>
    </header>
  )
}
