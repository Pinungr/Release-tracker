import { useCallback, useEffect, useState } from 'react'
import { api, userToken } from '../services/api'
import type { AuthSession, AuthUser } from '../types'

export function useAuthSession() {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    if (!userToken.get()) {
      setChecking(false)
      return
    }
    api.me().then(setUser).catch(() => userToken.clear()).finally(() => setChecking(false))
  }, [])

  const signIn = useCallback((session: AuthSession) => {
    userToken.set(session.access_token)
    setUser(session.user)
  }, [])

  const refreshUser = useCallback(async () => {
    const current = await api.me()
    setUser(current)
  }, [])

  const signOut = useCallback(async () => {
    try {
      await api.logout()
    } catch {
      // The local token is discarded even when the server session is already gone.
    }
    userToken.clear()
    setUser(null)
  }, [])

  const isManagement = user?.groups?.some((group) => group.group_type === 'MANAGEMENT') ?? false

  return {
    user,
    isAuthenticated: user !== null,
    // Management membership is authoritative and always read-only, even if a
    // stale legacy role still says ADMIN from an earlier RM assignment.
    isAdmin: user?.role === 'ADMIN' && !isManagement,
    isManagement,
    checking,
    signIn,
    signOut,
    refreshUser,
  }
}
