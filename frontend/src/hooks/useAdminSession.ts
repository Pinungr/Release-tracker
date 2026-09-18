import { useCallback, useEffect, useState } from 'react'
import { adminToken, api } from '../services/api'
import type { AdminSession } from '../types'

const NAME_KEY = 'pds.admin.username'

/**
 * Admin identity for the UI only. Every admin action is authorised again on
 * the server from the bearer token, so a tampered value here grants nothing.
 */
export function useAdminSession() {
  const [username, setUsername] = useState<string | null>(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    if (!adminToken.get()) {
      setChecking(false)
      return
    }
    api
      .adminMe()
      .then((me) => setUsername(me.username))
      .catch(() => {
        adminToken.clear()
        sessionStorage.removeItem(NAME_KEY)
        setUsername(null)
      })
      .finally(() => setChecking(false))
  }, [])

  const signIn = useCallback((session: AdminSession) => {
    adminToken.set(session.access_token)
    sessionStorage.setItem(NAME_KEY, session.username)
    setUsername(session.username)
  }, [])

  const signOut = useCallback(async () => {
    try {
      await api.adminLogout()
    } catch {
      // The token is discarded locally regardless of the response.
    }
    adminToken.clear()
    sessionStorage.removeItem(NAME_KEY)
    setUsername(null)
  }, [])

  return { username, isAdmin: username !== null, checking, signIn, signOut }
}
