import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import './demo.css'

export default function DemoSession() {
  const navigate = useNavigate()

  const [riskScore] = useState(18)
  const [logLines, setLogLines] = useState([])
  const [heartbeatCount, setHeartbeatCount] = useState(0)
  const [signals, setSignals] = useState({
    face_similarity: 0.94,
    ip_changed: false,
    hour_of_day: new Date().getHours(),
    failed_attempts: 0,
    session_age_min: 0,
    actions_per_min: 1.2,
    privilege_req: false,
  })
  const [loginTime] = useState(() => new Date().toLocaleTimeString())

  const timersRef = useRef([])

  // ---- heartbeat simulation + initial logs (runs once) ----
  useEffect(() => {
    const timers = timersRef.current
    const addLog = (text, type = 'default') => {
      const time = new Date().toLocaleTimeString()
      setLogLines(prev => [
        { text, type, time, id: Date.now() + Math.random() },
        ...prev,
      ].slice(0, 20))
    }

    // initial session logs at t=500ms
    timers.push(setTimeout(() => {
      addLog('[Session] JWT validated', 'success')
      addLog('[User] demo_user authenticated', 'success')
      addLog('[Session] Monitoring active')
    }, 500))

    // heartbeat every 8s (slow pace for the demo)
    const hb = setInterval(() => {
      setHeartbeatCount(c => c + 1)
      addLog('[Heartbeat] Frame received')
      addLog('[DeepFace] Similarity: 0.94', 'success')
      addLog('[Risk] Assembling signals...')
      timers.push(setTimeout(() => {
        addLog('[Gemma] Scoring session...')
        timers.push(setTimeout(() => {
          addLog('[Gemma] risk_score=18 — SAFE', 'success')
          addLog('[AuditLog] risk_score=18 written')
        }, 600))
      }, 800))
      setSignals(s => ({ ...s, session_age_min: s.session_age_min + 1 }))
    }, 8000)
    timers.push(hb)

    return () => {
      timers.forEach(id => { clearTimeout(id); clearInterval(id) })
      timersRef.current = []
    }
  }, [])

  const riskColor =
    riskScore >= 90 ? 'var(--danger)'
      : riskScore >= 70 ? 'var(--warning)'
        : 'var(--success)'

  const sessionSignals = [
    { key: 'face_similarity', val: signals.face_similarity.toFixed(2), cls: 'green' },
    { key: 'ip_changed',      val: String(signals.ip_changed),         cls: 'green' },
    { key: 'hour_of_day',     val: String(signals.hour_of_day),        cls: '' },
    { key: 'failed_attempts', val: String(signals.failed_attempts),    cls: 'green' },
    { key: 'session_age',     val: `${signals.session_age_min}m`,      cls: '' },
    { key: 'actions/min',     val: String(signals.actions_per_min),    cls: '' },
    { key: 'privilege_req',   val: String(signals.privilege_req),      cls: 'green' },
    { key: 'status',          val: 'SAFE',                             cls: 'green' },
  ]

  return (
    <div className="demo-page">
      <nav className="demo-nav">
        <span className="logo">🔐 AIRGAPPED ZTA</span>
        <span className="breadcrumb">Active Session</span>
        <span className="step-indicator">
          {[0, 1, 2, 3, 4, 5].map(i => (
            <span
              key={i}
              className={'step' + (i < 2 ? ' done' : i === 2 ? ' active' : '')}
            />
          ))}
        </span>
      </nav>

      <div className="session-grid">

        {/* LEFT — session info + signals */}
        <div className="session-col">
          <div className="demo-panel">
            <h2>Session Info</h2>
            <div className="info-row">
              <span className="info-key">User</span><span className="info-val">demo_user</span>
            </div>
            <div className="info-row">
              <span className="info-key">Role</span><span className="info-val">user</span>
            </div>
            <div className="info-row">
              <span className="info-key">Login time</span><span className="info-val">{loginTime}</span>
            </div>
            <div className="info-row">
              <span className="info-key">Heartbeats</span><span className="info-val">{heartbeatCount}</span>
            </div>
            <div className="info-row">
              <span className="info-key">Session age</span>
              <span className="info-val">{signals.session_age_min} min</span>
            </div>
          </div>

          <div className="demo-panel">
            <h2>Signal Monitor</h2>
            <div className="signal-grid">
              {sessionSignals.map(s => (
                <div key={s.key} className="signal-item">
                  <span className="signal-key">{s.key}</span>
                  <span className={'signal-val' + (s.cls ? ' ' + s.cls : '')}>{s.val}</span>
                </div>
              ))}
            </div>
          </div>

          <button className="demo-btn full" onClick={() => navigate('/demo/attack')}>
            ⚠️ Simulate Attack
          </button>
          <button
            className="demo-btn secondary full"
            style={{ marginTop: '0.5rem' }}
            onClick={() => window.open('/demo/admin', '_blank')}
          >
            👑 Admin Panel ↗
          </button>
        </div>

        {/* CENTER — risk score + gemma */}
        <div className="session-col">
          <div className="demo-panel">
            <h2>Risk Score</h2>
            <div className="risk-wrap">
              <div className="risk-score-number" style={{ color: riskColor }}>
                {riskScore}
              </div>
              <div className="risk-label" style={{ color: riskColor }}>SAFE</div>
              <div className="risk-bar-track">
                <div
                  className="risk-bar-fill"
                  style={{ width: `${riskScore}%`, background: riskColor }}
                />
              </div>
            </div>
          </div>

          <div className="demo-panel">
            <h2>Gemma Analysis</h2>
            <div className="gemma-box">{`{"risk_score": 18,
 "reason": "All signals nominal.
 Face match strong at 0.94.
 No anomalies detected."}`}</div>
            <div className="risk-meta">
              <div>Model: Gemma 2B (local)</div>
              <div>Endpoint: localhost:1234/v1</div>
            </div>
          </div>
        </div>

        {/* RIGHT — scrolling terminal log */}
        <div className="session-col">
          <div className="demo-panel session-log-panel">
            <h2>System Log</h2>
            <div className="terminal-log">
              {logLines.map(line => (
                <div key={line.id} className={'log-line ' + line.type}>
                  <span className="log-time">{line.time}</span>
                  {line.text}
                </div>
              ))}
            </div>
          </div>
        </div>

      </div>
    </div>
  )
}
