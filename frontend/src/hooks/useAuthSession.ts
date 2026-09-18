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

  const signOut = useCallback(async () => {
    try {
      await api.logout()
    } catch {
      // The local token is discarded even when the server session is already gone.
    }
    userToken.clear()
    setUser(null)
  }, [])

  return { user, isAuthenticated: user !== null, isAdmin: user?.role === 'ADMIN', checking, signIn, signOut }
}
