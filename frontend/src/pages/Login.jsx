import { useState, useCallback, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import LivenessCamera from '../components/LivenessCamera'
import './Login.css'

export default function Login() {
  const navigate = useNavigate()
  const { login, isAuthenticated } = useAuth()

  // Redirect if already logged in
  useEffect(() => {
    if (isAuthenticated) navigate('/dashboard')
  }, [isAuthenticated, navigate])

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [fieldErrors, setFieldErrors] = useState({})

  const [capturedBlob,      setCapturedBlob]      = useState(null)
  const [capturedChallenge, setCapturedChallenge] = useState(null)

  const [submitting,   setSubmitting]   = useState(false)
  const [banner,       setBanner]       = useState({ msg: '', type: '' })
  const [lockMessage,  setLockMessage]  = useState(null)

  // Key to remount LivenessCamera (force new challenge
  // after a failed attempt so user must re-verify)
  const [cameraKey, setCameraKey] = useState(0)

  const handleCapture = useCallback(
    (blob, dataUrl, challengeType) => {
      setCapturedBlob(blob)
      setCapturedChallenge(challengeType)
      setBanner({ msg: '', type: '' })
    }, []
  )

  const handleCameraError = useCallback((msg) => {
    setBanner({ msg, type: 'error' })
  }, [])

  function resetCamera() {
    setCapturedBlob(null)
    setCapturedChallenge(null)
    setCameraKey(k => k + 1)
  }

  function validate() {
    const errs = {}
    if (!username.trim())
      errs.username = 'Username is required'
    if (!password)
      errs.password = 'Password is required'
    return errs
  }

  async function handleSubmit() {
    if (!capturedBlob) {
      setBanner({
        msg: 'Complete the liveness challenge first',
        type: 'error'
      })
      return
    }

    const errs = validate()
    if (Object.keys(errs).length > 0) {
      setFieldErrors(errs)
      return
    }
    setFieldErrors({})
    setSubmitting(true)
    setBanner({ msg: '', type: '' })

    try {
      const fd = new FormData()
      fd.append('username',       username.trim())
      fd.append('password',       password)
      fd.append('challenge_type', capturedChallenge)
      fd.append('image',          capturedBlob, 'face.jpg')

      const res = await fetch('/auth/login', {
        method: 'POST',
        body: fd,
      })

      const data = await res.json()

      if (res.ok) {
        // Store JWT in AuthContext memory
        login(data)
        setBanner({
          msg: '✅ Login successful! Redirecting...',
          type: 'success'
        })
        setTimeout(() => navigate('/dashboard'), 1200)

      } else if (res.status === 403) {
        // Locked: either a timed lock after failed attempts or disabled by
        // an admin / the risk engine. The server's message says which.
        setLockMessage(data.detail || 'Account locked.')
        setBanner({ msg: '', type: '' })
        setSubmitting(false)

      } else if (res.status === 429) {
        setBanner({
          msg: 'Too many attempts from this device. Wait a minute and try again.',
          type: 'error'
        })
        resetCamera()
        setSubmitting(false)

      } else if (res.status === 401) {
        // The server deliberately gives one generic message for any wrong
        // credential, so it cannot be used to discover accounts.
        setBanner({ msg: data.detail || 'Invalid credentials', type: 'error' })
        // Force new liveness challenge on retry
        resetCamera()
        setSubmitting(false)

      } else {
        setBanner({
          msg: data.detail || 'Login failed',
          type: 'error'
        })
        resetCamera()
        setSubmitting(false)
      }

    } catch {
      setBanner({
        msg: 'Network error — is the backend running?',
        type: 'error'
      })
      resetCamera()
      setSubmitting(false)
    }
  }

  // Locked state — show full-page message
  if (lockMessage) return (
    <div className="login-page">
      <div className="login-card">
        <div className="locked-box">
          <h2>🔒 Account Locked</h2>
          <p>{lockMessage}</p>
          {lockMessage.includes('temporarily') && (
            <button
              className="btn-primary"
              onClick={() => { setLockMessage(null); resetCamera() }}
            >
              Try again
            </button>
          )}
        </div>
      </div>
    </div>
  )

  return (
    <div className="login-page">
      <div className="login-card">

        {/* Header */}
        <div className="login-header">
          <h1>🔐 AirGapped ZTA</h1>
          <p>Two-factor biometric login</p>
        </div>

        {/* LEFT — credentials */}
        <div className="panel">
          <h2>Credentials</h2>

          <div className="form-group">
            <label>Username</label>
            <input
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="Your username"
              className={fieldErrors.username ? 'error' : ''}
              disabled={submitting}
              autoComplete="username"
            />
            {fieldErrors.username && (
              <div className="field-error">
                {fieldErrors.username}
              </div>
            )}
          </div>

          <div className="form-group">
            <label>Password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="Your password"
              className={fieldErrors.password ? 'error' : ''}
              disabled={submitting}
              autoComplete="current-password"
            />
            {fieldErrors.password && (
              <div className="field-error">
                {fieldErrors.password}
              </div>
            )}
          </div>
        </div>

        {/* RIGHT — liveness camera */}
        <div className="panel">
          <h2>Face Verification</h2>
          <LivenessCamera
            key={cameraKey}
            onCapture={handleCapture}
            onError={handleCameraError}
          />
        </div>

        {/* FOOTER */}
        <div className="login-footer">
          <button
            className="btn-primary"
            onClick={handleSubmit}
            disabled={submitting || !capturedBlob}
          >
            {submitting ? 'Verifying...' : 'Login'}
          </button>

          <div className={
            'status-banner ' +
            (banner.msg ? 'visible ' : '') +
            banner.type
          }>
            {banner.msg}
          </div>

          <p className="enroll-link">
            New user?{' '}
            <Link to="/enroll">Enroll here</Link>
          </p>
        </div>

      </div>
    </div>
  )
}
