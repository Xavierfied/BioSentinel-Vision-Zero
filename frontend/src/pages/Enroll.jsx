import { useState, useCallback } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import LivenessCamera from '../components/LivenessCamera'
import './Enroll.css'

export default function Enroll() {
  const navigate = useNavigate()

  // Form fields
  const [username, setUsername] = useState('')
  const [email,    setEmail]    = useState('')
  const [password, setPassword] = useState('')

  // Field-level validation errors
  const [fieldErrors, setFieldErrors] = useState({})

  // Captured face data from LivenessCamera
  const [capturedBlob,      setCapturedBlob]      = useState(null)
  const [capturedChallenge, setCapturedChallenge] = useState(null)

  // Submission state
  const [submitting, setSubmitting] = useState(false)
  const [banner,     setBanner]     = useState({ msg: '', type: '' })

  const handleCapture = useCallback(
    (blob, dataUrl, challengeType) => {
      setCapturedBlob(blob)
      setCapturedChallenge(challengeType)
    }, []
  )

  const handleCameraError = useCallback((msg) => {
    setBanner({ msg, type: 'error' })
  }, [])

  function validate() {
    const errs = {}
    if (username.trim().length < 3)
      errs.username = 'Min 3 characters'
    if (username.trim().length > 50)
      errs.username = 'Max 50 characters'
    if (!/\S+@\S+\.\S+/.test(email))
      errs.email = 'Enter a valid email'
    if (password.length < 8)
      errs.password = 'Min 8 characters'
    return errs
  }

  async function handleSubmit() {
    // Must have captured a face first
    if (!capturedBlob) {
      setBanner({
        msg: 'Complete the liveness challenge first',
        type: 'error'
      })
      return
    }

    // Validate form fields
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
      fd.append('email',          email.trim())
      fd.append('password',       password)
      fd.append('challenge_type', capturedChallenge)
      fd.append('image',          capturedBlob, 'face.jpg')

      const res = await fetch('/enroll/', {
        method: 'POST',
        body: fd,
      })

      const data = await res.json()

      if (res.ok) {
        setBanner({
          msg: '✅ Enrolled successfully! Redirecting to login...',
          type: 'success'
        })
        setTimeout(() => navigate('/login'), 1800)
      } else {
        setBanner({
          msg: data.detail || 'Enrollment failed',
          type: 'error'
        })
        setSubmitting(false)
      }
    } catch (err) {
      setBanner({
        msg: 'Network error — is the backend running?',
        type: 'error'
      })
      setSubmitting(false)
    }
  }

  return (
    <div className="enroll-page">

      <div className="enroll-header">
        <h1>🔐 AirGapped ZTA</h1>
        <p>Biometric Enrollment — register your identity</p>
      </div>

      <div className="enroll-grid">

        {/* LEFT — account form */}
        <div className="panel">
          <h2>Account Details</h2>

          <div className="form-group">
            <label>Username</label>
            <input
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="Choose a username"
              className={fieldErrors.username ? 'error' : ''}
              disabled={submitting}
            />
            {fieldErrors.username && (
              <div className="field-error">
                {fieldErrors.username}
              </div>
            )}
          </div>

          <div className="form-group">
            <label>Email</label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="your@email.com"
              className={fieldErrors.email ? 'error' : ''}
              disabled={submitting}
            />
            {fieldErrors.email && (
              <div className="field-error">
                {fieldErrors.email}
              </div>
            )}
          </div>

          <div className="form-group">
            <label>Password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="Min 8 characters"
              className={fieldErrors.password ? 'error' : ''}
              disabled={submitting}
            />
            {fieldErrors.password && (
              <div className="field-error">
                {fieldErrors.password}
              </div>
            )}
          </div>
        </div>

        {/* RIGHT — webcam + liveness */}
        <div className="panel">
          <h2>Face Capture</h2>
          <LivenessCamera
            onCapture={handleCapture}
            onError={handleCameraError}
          />
        </div>

        {/* FOOTER — submit + status */}
        <div className="enroll-footer">
          <button
            className="btn-primary"
            onClick={handleSubmit}
            disabled={submitting || !capturedBlob}
          >
            {submitting
              ? 'Enrolling...'
              : 'Complete Enrollment'}
          </button>

          <div className={
            'status-banner ' +
            (banner.msg ? 'visible ' : '') +
            banner.type
          }>
            {banner.msg}
          </div>

          <p className="login-link">
            Already enrolled?{' '}
            <Link to="/login">Log in here</Link>
          </p>
        </div>

      </div>
    </div>
  )
}
