import { createContext, useContext, useState, useCallback }
  from 'react'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  // JWT stored in memory only — never localStorage
  const [accessToken, setAccessToken]   = useState(null)
  const [refreshToken, setRefreshToken] = useState(null)
  const [user, setUser] = useState(null)

  const login = useCallback((tokenData) => {
    // tokenData = { access_token, refresh_token,
    //               token_type, expires_in }
    setAccessToken(tokenData.access_token)
    setRefreshToken(tokenData.refresh_token)

    // Decode JWT payload (no verification — backend
    // already verified)
    try {
      const payload = JSON.parse(
        atob(tokenData.access_token.split('.')[1])
      )
      setUser({
        id:       payload.sub,
        username: payload.username,
        role:     payload.role,
      })
    } catch {
      setUser(null)
    }
  }, [])

  const logout = useCallback(() => {
    setAccessToken(null)
    setRefreshToken(null)
    setUser(null)
  }, [])

  const authFetch = useCallback(async (url, options = {}) => {
    // Wrapper around fetch that injects the Bearer token.
    // Use this for all authenticated API calls.
    return fetch(url, {
      ...options,
      headers: {
        ...options.headers,
        ...(accessToken
          ? { Authorization: `Bearer ${accessToken}` }
          : {}),
      },
    })
  }, [accessToken])

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
