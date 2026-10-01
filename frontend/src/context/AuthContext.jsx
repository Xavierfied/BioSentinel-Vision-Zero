import { createContext, useContext, useState, useCallback, useRef }
  from 'react'

const AuthContext = createContext(null)

function decodeUser(accessToken) {
  // Display only: the server verifies every token on every request.
  try {
    const payload = JSON.parse(atob(accessToken.split('.')[1]))
    return { id: payload.sub, username: payload.username, role: payload.role }
  } catch {
    return null
  }
}

export function AuthProvider({ children }) {
  // JWT stored in memory only — never localStorage
  const [accessToken, setAccessToken]   = useState(null)
  const [refreshToken, setRefreshToken] = useState(null)
  const [user, setUser] = useState(null)

  // Refs so authFetch always sees the latest tokens, even mid-refresh.
  const accessRef   = useRef(null)
  const refreshRef  = useRef(null)
  const refreshing  = useRef(null)

  const setTokens = useCallback((tokenData) => {
    accessRef.current  = tokenData?.access_token  ?? null
    refreshRef.current = tokenData?.refresh_token ?? null
    setAccessToken(accessRef.current)
    setRefreshToken(refreshRef.current)
    setUser(accessRef.current ? decodeUser(accessRef.current) : null)
  }, [])

  const login = useCallback((tokenData) => {
    // tokenData = { access_token, refresh_token, token_type, expires_in }
    setTokens(tokenData)
  }, [setTokens])

  const logout = useCallback(async () => {
    const token = accessRef.current
    setTokens(null)
    if (token) {
      // End the session server-side so the tokens stop working everywhere.
      try {
        await fetch('/auth/logout', {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        })
      } catch { /* already logged out locally */ }
    }
  }, [setTokens])

  // One refresh at a time: concurrent 401s wait for the same attempt,
  // because each refresh token only works once.
  const refresh = useCallback(() => {
    if (!refreshing.current) {
      refreshing.current = (async () => {
        const token = refreshRef.current
        if (!token) return false
        try {
          const res = await fetch('/auth/refresh', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: token }),
          })
          if (!res.ok) { setTokens(null); return false }
          setTokens(await res.json())
          return true
        } catch {
          return false
        } finally {
          refreshing.current = null
        }
      })()
    }
    return refreshing.current
  }, [setTokens])

  const authFetch = useCallback(async (url, options = {}) => {
    // Wrapper around fetch that injects the Bearer token and, on a 401,
    // refreshes once and retries. Use this for all authenticated calls.
    const send = () => fetch(url, {
      ...options,
      headers: {
        ...options.headers,
        ...(accessRef.current
          ? { Authorization: `Bearer ${accessRef.current}` }
          : {}),
      },
    })
    const res = await send()
    if (res.status !== 401 || !refreshRef.current) return res
    return (await refresh()) ? send() : res
  }, [refresh])

  return (
    <AuthContext.Provider value={{
      accessToken, refreshToken, user,
      login, logout, authFetch,
      isAuthenticated: !!accessToken
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error(
    'useAuth must be used inside AuthProvider'
  )
  return ctx
}
