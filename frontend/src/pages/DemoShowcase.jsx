import { useEffect, useRef, useState } from 'react'
import './DemoShowcase.css'

// Scene state machine — drives the entire page.
const SCENES = {
  0: 'idle',
  1: 'enrollment',
  2: 'login',
  3: 'session',
  4: 'attack',
  5: 'lockout',
}

// Left-column "current scene" readout.
const SCENE_INFO = {
  0: { name: 'Idle',             step: 'Awaiting demo start' },
  1: { name: 'Enrollment',       step: 'Capturing 128-d face embedding' },
  2: { name: 'Login',            step: 'Two-factor verification' },
  3: { name: 'Active Session',   step: 'Continuous risk monitoring' },
  4: { name: 'Attack Simulation',step: 'Anomaly → step-up' },
  5: { name: 'Lockout + Admin',  step: 'Lockout → admin unblock' },
}

// Fresh signal snapshot — hour_of_day reflects the real clock.
function defaultSignals() {
  return {
    face_similarity: '0.94',
    ip_changed:      'false',
    hour_of_day:     String(new Date().getHours()),
    failed_attempts: '0',
    session_age:     '4 min',
    actions_per_min: '1.2',
    privilege_req:   'false',
  }
}

// Terminal colour-coding. Matched in priority order: red → amber → green.
// "unblock" is excluded from the red "lock" rule so admin-unblock lines stay neutral.
function logLevel(text) {
  const s = text.toLowerCase()
  if ((s.includes('lock') && !s.includes('unblock')) ||
      s.includes('revok') || text.includes('🔒')) return 'red'
  if (s.includes('warn') || text.includes('risk_score=7') ||
      text.includes('⚠️')) return 'amber'
  if (text.includes('PASS') || s.includes('success') ||
      text.includes('✅')) return 'green'
  return ''
}

function riskColor(score) {
  if (score >= 90) return 'var(--danger)'
  if (score >= 70) return 'var(--warning)'
  return 'var(--success)'
}

export default function DemoShowcase() {
  const [scene, setScene]                     = useState(0)
  const [controllerHidden, setControllerHidden] = useState(false)
  const [cameraError, setCameraError]         = useState(false)
  const [logs, setLogs]                       = useState([])

  // Risk gauge (shared by scenes 3-5)
  const [riskScore, setRiskScore] = useState(0)
  const [riskLabel, setRiskLabel] = useState('')

  // Scene 1 — enrollment
  const [typedUsername, setTypedUsername] = useState('')
  const [typedEmail, setTypedEmail]       = useState('')
  const [typingField, setTypingField]     = useState(null)
  const [enrollComplete, setEnrollComplete] = useState(false)

  // Scene 2 — login
  const [loginDots, setLoginDots]               = useState(0)
  const [livenessVerified, setLivenessVerified] = useState(false)
  const [jwtIssued, setJwtIssued]               = useState(false)

  // Scenes 3 & 4 — monitoring
  const [signals, setSignals]   = useState(defaultSignals)
  const [redKeys, setRedKeys]   = useState([])
  const [gemmaText, setGemmaText] = useState('')
  const [alertShow, setAlertShow] = useState(false)

  // Scene 5 — lockout + admin
  const [lockBanner, setLockBanner]         = useState(false)
  const [adminView, setAdminView]           = useState(false)
  const [unblockPulse, setUnblockPulse]     = useState(false)
  const [unblockPressed, setUnblockPressed] = useState(false)
  const [unblockDone, setUnblockDone]       = useState(false)
  const [userActive, setUserActive]         = useState(false)

  const videoRef    = useRef(null)
  const canvasRef   = useRef(null)
  const cameraRef   = useRef(null)   // MediaPipe Camera instance — stopped on unmount
  const timersRef   = useRef([])     // every setTimeout/setInterval id for this scene
  const logIdRef    = useRef(0)
  const riskRef     = useRef(0)      // mirrors riskScore for rAF tween start value
  const riskRafRef  = useRef(null)

  // ---- timer helpers (all ids tracked so a scene change clears them) ----
  function clearTimers() {
    timersRef.current.forEach(id => { clearTimeout(id); clearInterval(id) })
    timersRef.current = []
    if (riskRafRef.current) cancelAnimationFrame(riskRafRef.current)
  }

  function after(delay, fn) {
    const id = setTimeout(fn, delay)
    timersRef.current.push(id)
    return id
  }

  function typeInto(text, setter, { charDelay = 80, onDone } = {}) {
    let i = 0
    const id = setInterval(() => {
      i += 1
      setter(text.slice(0, i))
      if (i >= text.length) {
        clearInterval(id)
        onDone?.()
      }
    }, charDelay)
    timersRef.current.push(id)
  }

  function staggerLogs(lines, startDelay = 0, gap = 400) {
    lines.forEach((line, i) => after(startDelay + i * gap, () => addLog(line)))
  }

  function addLog(text) {
    setLogs(prev => [
      { id: logIdRef.current++, text, level: logLevel(text),
        time: new Date().toLocaleTimeString() },
      ...prev,
    ].slice(0, 20))
  }

  // ---- risk gauge ----
  function setRisk(v) { setRiskScore(v); riskRef.current = v }

  function animateRiskTo(target, duration = 800) {
    if (riskRafRef.current) cancelAnimationFrame(riskRafRef.current)
    const start = riskRef.current
    const t0 = performance.now()
    const step = (now) => {
      const t = Math.min(1, (now - t0) / duration)
      const val = Math.round(start + (target - start) * t)
      setRiskScore(val)
      riskRef.current = val
      if (t < 1) riskRafRef.current = requestAnimationFrame(step)
    }
    riskRafRef.current = requestAnimationFrame(step)
  }

  function doUnblock() {
    setUserActive(true)
    setUnblockPulse(false)
    setUnblockDone(true)
    addLog('[Admin] POST /admin/unblock/6')
    addLog('[DB] is_active=True, sessions revoked')
    addLog('[AuditLog] action=admin_unblock')
    addLog('[System] User may now re-authenticate')
  }

  // ---- webcam (real camera) — start once on mount ----
  useEffect(() => {
    let stream
    navigator.mediaDevices.getUserMedia({ video: true })
      .then(s => { stream = s; if (videoRef.current) videoRef.current.srcObject = s })
      .catch(() => setCameraError(true))
    return () => { if (stream) stream.getTracks().forEach(t => t.stop()) }
  }, [])

  // ---- MediaPipe face mesh overlay — runs once after mount ----
  useEffect(() => {
    if (!window.FaceMesh || !window.Camera) return
    if (!videoRef.current) return

    const faceMesh = new window.FaceMesh({
      locateFile: f =>
        `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh@0.4/${f}`
    })
    faceMesh.setOptions({
      maxNumFaces: 1,
      refineLandmarks: false,
      minDetectionConfidence: 0.5,
      minTrackingConfidence: 0.5,
    })
    faceMesh.onResults(results => {
      const canvas = canvasRef.current
      const video  = videoRef.current
      if (!canvas || !video) return

      const ctx = canvas.getContext('2d')
      canvas.width  = video.videoWidth  || 640
      canvas.height = video.videoHeight || 480
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(results.image, 0, 0, canvas.width, canvas.height)

      const lmList = results.multiFaceLandmarks
      if (!lmList || lmList.length === 0) return
      const landmarks = lmList[0]

      window.drawConnectors(ctx, landmarks,
        window.FACEMESH_TESSELATION,
        { color: '#1a1a3a', lineWidth: 0.5 })
      window.drawConnectors(ctx, landmarks,
        window.FACEMESH_FACE_OVAL,
        { color: '#6c63ff', lineWidth: 2 })
    })

    const cam = new window.Camera(videoRef.current, {
      onFrame: async () => {
        await faceMesh.send({ image: videoRef.current })
      },
      width: 640,
      height: 480,
    })
    cam.start()
    cameraRef.current = cam

    return () => {
      cam.stop()
      faceMesh.close()
    }
  }, [])

  // ---- keyboard: 1-5 jump scenes, 0 idle, ` toggles controller ----
  useEffect(() => {
    function onKey(e) {
      if (e.key === '`') { setControllerHidden(h => !h); return }
      const n = parseInt(e.key, 10)
      if (n >= 0 && n <= 5) setScene(n)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // ---- scene driver: reset shared state, then run the scene's timeline ----
  useEffect(() => {
    clearTimers()
    // Clean slate so animations never bleed between scenes.
    setRedKeys([])
    setAlertShow(false)
    setLockBanner(false)
    setAdminView(false)
    setUnblockPulse(false)
    setUnblockPressed(false)
    setUnblockDone(false)
    setUserActive(false)

    if (scene === 0) {
      setRisk(0)
      setRiskLabel('')
    }

    if (scene === 1) {
      setTypedUsername('')
      setTypedEmail('')
      setTypingField(null)
      setEnrollComplete(false)
      after(500, () => {
        setTypingField('username')
        typeInto('demo_user', setTypedUsername, {
          onDone: () => {
            setTypingField('email')
            typeInto('demo@ztasystem.local', setTypedEmail, {
              onDone: () => {
                setTypingField(null)
                after(2000, () => setEnrollComplete(true))
              },
            })
          },
        })
      })
      staggerLogs([
        '[YOLOv8] Face detected — confidence 0.94',
        '[RetinaFace] Step-up not required',
        '[DeepFace] Embedding extracted — 128d Facenet',
        '[DB] User demo_user enrolled successfully',
        '[AuditLog] action=enroll user_id=6',
      ], 800, 400)
    }

    if (scene === 2) {
      setLoginDots(0)
      setLivenessVerified(false)
      setJwtIssued(false)
      after(600,  () => setLoginDots(1))
      after(1200, () => setLoginDots(2))
      after(1800, () => { setLoginDots(3); setLivenessVerified(true) })
      after(3300, () => setJwtIssued(true))
      staggerLogs([
        '[Auth] bcrypt verify — PASS',
        '[YOLOv8] Face detected — confidence 0.91',
        '[DeepFace] Live embedding extracted',
        '[Similarity] 0.94 ≥ 0.60 threshold — MATCH',
        '[JWT] Token pair issued — session saved',
        '[AuditLog] action=login_success similarity=0.94',
      ], 600, 400)
    }

    if (scene === 3) {
      setSignals(defaultSignals())
      setRisk(18)
      setRiskLabel('RISK SCORE — SAFE')
      setGemmaText('{"risk_score": 18, "reason": "All signals nominal. ' +
        'Face match strong, no anomalies detected."}')
      staggerLogs([
        '[Heartbeat] Frame received',
        '[DeepFace] Similarity: 0.94',
        '[Risk] Assembling signals...',
        '[Gemma] Scoring session...',
        '[Gemma] risk_score=18 — SAFE',
        '[AuditLog] risk_score=18 written',
      ], 500, 400)
    }

    if (scene === 4) {
      setSignals(defaultSignals())
      setRisk(18)
      setRiskLabel('RISK SCORE — SAFE')
      setGemmaText('{"risk_score": 18, "reason": "All signals nominal. ' +
        'Face match strong, no anomalies detected."}')

      after(0, () => {
        setSignals(s => ({ ...s, ip_changed: 'true' }))
        setRedKeys(['ip_changed'])
        addLog('[Demo] IP shift signal injected')
        addLog('[Demo] Spam requests injected (20 entries)')
      })
      after(1200, () => {
        animateRiskTo(45)
        addLog('[Risk] Reassembling signals...')
        addLog('[Gemma] Analysing anomalies...')
      })
      after(2400, () => {
        animateRiskTo(72)
        setRiskLabel('ELEVATED RISK')
        setGemmaText('{"risk_score": 72, "reason": "IP change detected. ' +
          'Unusual request rate. Step-up required."}')
        addLog('[Gemma] risk_score=72 ≥ threshold 70')
      })
      after(3600, () => {
        setAlertShow(true)
        addLog('[RiskMiddleware] JWT revoked')
        addLog('[Session] is_revoked=True')
        addLog('[Response] 401 — step_up_required')
      })
    }

    if (scene === 5) {
      setSignals({ ...defaultSignals(), ip_changed: 'true' })
      setRedKeys(['ip_changed'])
      setRisk(92)
      setRiskLabel('CRITICAL RISK — LOCKOUT')
      setGemmaText('{"risk_score": 92, "reason": "Multiple critical anomalies. ' +
        'Account locked pending admin review."}')

      after(0, () => {
        addLog('[Gemma] risk_score=92 ≥ threshold 90')
        addLog('[RiskMiddleware] Lockout triggered')
        addLog('[DB] user.is_active = False')
      })
      after(1000, () => setLockBanner(true))
      after(2000, () => setAdminView(true))
      after(3500, () => setUnblockPulse(true))
      after(4500, () => setUnblockPressed(true))   // simulated admin click
      after(5000, () => doUnblock())
    }

    return clearTimers
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene])

  // ---- center-panel render per scene ----
  function renderGauge() {
    return (
      <div className="risk-wrap">
        <div className="risk-score-number" style={{ color: riskColor(riskScore) }}>
          {riskScore}
        </div>
        <div className="risk-label">{riskLabel}</div>
        <div className="risk-bar-track">
          <div className="risk-bar-fill"
               style={{ width: `${riskScore}%`, background: riskColor(riskScore) }} />
        </div>
      </div>
    )
  }

  function renderSignals() {
    return (
      <div className="signal-grid">
        {Object.entries(signals).map(([k, v]) => (
          <div key={k} className="signal-item">
            <span className="signal-key">{k}</span>
            <span className={'signal-val' + (redKeys.includes(k) ? ' red' : '')}>{v}</span>
          </div>
        ))}
      </div>
    )
  }

  function renderCenter() {
    if (scene === 0) return (
      <div className="center-scene idle-scene">
        <div className="idle-title">AirGapped ZTA</div>
        <div className="idle-sub">Zero-Trust Biometric Authentication</div>
        <div className="idle-sub2">Press 1 to begin demo</div>
      </div>
    )

    if (scene === 1) return (
      <div className="center-scene">
        <h2 className="scene-header">👤 New User Enrollment</h2>
        <label className="form-demo-label">Username</label>
        <div className="form-demo-field">
          {typedUsername}
          {typingField === 'username' && <span className="typing-cursor" />}
        </div>
        <label className="form-demo-label">Email</label>
        <div className="form-demo-field">
          {typedEmail}
          {typingField === 'email' && <span className="typing-cursor" />}
        </div>
        <label className="form-demo-label">Password</label>
        <div className="form-demo-field">••••••••••</div>

        {enrollComplete && (
          <div className="success-box">
            <div className="success-title">✅ Enrollment Complete</div>
            <div>Face embedding stored — 128 dimensions</div>
            <div>YOLOv8 → RetinaFace → DeepFace pipeline</div>
          </div>
        )}
      </div>
    )

    if (scene === 2) return (
      <div className="center-scene">
        <h2 className="scene-header">🔐 Two-Factor Authentication</h2>
        <div className="factor-grid">
          <div className="factor-panel">
            <h4>Factor 1 — Credentials</h4>
            <label className="form-demo-label">Username</label>
            <div className="form-demo-field">demo_user</div>
            <label className="form-demo-label">Password</label>
            <div className="form-demo-field">••••••••••</div>
            <div className="check-item"><span className="ok">✅</span> Password verified</div>
          </div>
          <div className="factor-panel">
            <h4>Factor 2 — Biometric</h4>
            <div className="challenge-tag">Challenge: BLINK BOTH EYES</div>
            <div className="progress-dots-demo">
              {[1, 2, 3].map(i => (
                <span key={i} className={'pd' + (i <= loginDots ? ' on' : '')} />
              ))}
            </div>
            {livenessVerified && (
              <>
                <div className="check-item"><span className="ok">✅</span> Liveness verified</div>
                <div className="check-sub">Cosine similarity: 0.94</div>
                <div className="check-sub">Threshold: 0.60 ✅</div>
              </>
            )}
          </div>
        </div>

        {jwtIssued && (
          <div className="jwt-panel">
            <div className="jwt-title">JWT Issued</div>
            <div>Access token: eyJhbGciOiJIUzI1NiJ9.••••••••</div>
            <div>Expires: 30 minutes</div>
            <div>Role: user</div>
          </div>
        )}
      </div>
    )

    if (scene === 3) return (
      <div className="center-scene">
        <h2 className="scene-header">🟢 Session Active — Risk Monitoring</h2>
        {renderGauge()}
        <div className="risk-subtitle">Gemma evaluating signals every 60s</div>
        {renderSignals()}
        <div className="gemma-box">{gemmaText}</div>
      </div>
    )

    if (scene === 4) return (
      <div className="center-scene">
        <h2 className="scene-header">⚠️ Anomaly Detected</h2>
        {renderGauge()}
        {renderSignals()}
        <div className="gemma-box">{gemmaText}</div>
        {alertShow && (
          <div className="alert-banner">
            <div className="alert-title">⚠️ STEP-UP AUTHENTICATION REQUIRED</div>
            <div className="alert-sub">Session terminated — re-verification needed</div>
          </div>
        )}
      </div>
    )

    if (scene === 5) return (
      <div className="center-scene">
        {!adminView ? (
          <>
            <h2 className="scene-header">🔒 Critical Risk — Account Lockout</h2>
            {renderGauge()}
            {lockBanner && (
              <div className="status-banner danger lock-banner">
                <div className="lock-title">🔒 ACCOUNT LOCKED</div>
                <div>Administrator action required</div>
              </div>
            )}
          </>
        ) : (
          <>
            <h2 className="scene-header">👑 Admin Panel</h2>
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Username</th><th>Role</th><th>Status</th><th>Action</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>demo_user</td>
                  <td>user</td>
                  <td>{userActive ? '🟢 Active' : '🔴 LOCKED'}</td>
                  <td>
                    {userActive ? '—' : (
                      <button
                        className={'unblock-btn' +
                          (unblockPulse ? ' pulse' : '') +
                          (unblockPressed ? ' pressed' : '')}
                        onClick={doUnblock}
                      >
                        Unblock
                      </button>
                    )}
                  </td>
                </tr>
                <tr>
                  <td>admin</td><td>admin</td><td>🟢 Active</td><td>—</td>
                </tr>
              </tbody>
            </table>
            {unblockDone && (
              <div className="success-box">
                <div className="success-title">✅ User unblocked</div>
              </div>
            )}
          </>
        )}
      </div>
    )

    return null
  }

  const info = SCENE_INFO[scene]

  return (
    <div className="demo-page">

      {/* LEFT — webcam + scene readout */}
      <div className="demo-col demo-col--left">
        <div className="demo-panel">
          <h3>Live Camera</h3>
          <div className="webcam-wrapper">
            <video ref={videoRef} autoPlay playsInline muted />
            <canvas ref={canvasRef} />
            {cameraError && (
              <div className="webcam-error">📷 Camera unavailable</div>
            )}
          </div>
        </div>
        <div className="demo-panel">
          <h3>Scene</h3>
          <div className="scene-name">{info.name}</div>
          <div className="scene-step">{info.step}</div>
        </div>
      </div>

      {/* CENTER — scripted scene content */}
      <div className="demo-col demo-col--center">
        <div className="demo-panel demo-panel--fill center-panel">
          {renderCenter()}
        </div>
      </div>

      {/* RIGHT — system log */}
      <div className="demo-col demo-col--right">
        <div className="demo-panel demo-panel--fill">
          <h3>System Log</h3>
          <div className="terminal-log">
            {logs.map(l => (
              <div key={l.id} className={'log-line ' + l.level}>
                <span className="log-time">{l.time}</span>{l.text}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* CONTROLLER — hidden during recording (backtick toggles) */}
      <div className={'controller-bar' + (controllerHidden ? ' hidden' : '')}>
        {[1, 2, 3, 4, 5].map(n => (
          <button
            key={n}
            className={'scene-btn' + (scene === n ? ' active' : '')}
            onClick={() => setScene(n)}
          >
            {n} · {SCENES[n][0].toUpperCase() + SCENES[n].slice(1)}
          </button>
        ))}
        <span className="controller-hint">
          Press 1–5 to advance scenes · ` to hide
        </span>
      </div>

    </div>
  )
}
