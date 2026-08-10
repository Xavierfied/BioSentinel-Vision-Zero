import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import './demo.css'

export default function DemoAttack() {
  const navigate = useNavigate()

  // 0 normal · 1 signals injected · 2 climbing · 3 step-up · 4 escalating · 5 lockout
  const [phase, setPhase] = useState(0)
  const [riskScore, setRiskScore] = useState(18)
  const [logLines, setLogLines] = useState([])
  // eslint-disable-next-line no-unused-vars
  const [signals, setSignals] = useState({
    face_similarity: 0.94,
    ip_changed: false,
    failed_attempts: 0,
    actions_per_min: 1.2,
    privilege_req: false,
  })

  const timersRef = useRef([])

  // ---- scripted attack escalation (runs once) ----
  useEffect(() => {
    const timers = timersRef.current
    const addLog = (text, type = 'default') => {
      const time = new Date().toLocaleTimeString()
      setLogLines(prev => [
        { text, type, time, id: Date.now() + Math.random() },
        ...prev,
      ].slice(0, 20))
    }
    const at = (ms, fn) => { timers.push(setTimeout(fn, ms)) }

    addLog('[Session] Risk monitoring active')
    addLog('[Heartbeat] Baseline — risk=18', 'success')

    at(1500, () => {
      setPhase(1)
      setSignals(s => ({ ...s, ip_changed: true, actions_per_min: 18.4, failed_attempts: 2 }))
      addLog('[Demo] IP shift signal injected', 'warning')
      addLog('[Demo] Spam requests injected (20)', 'warning')
      addLog('[Risk] Anomalous signals detected', 'warning')
    })
    at(3000, () => {
      setPhase(2)
      setRiskScore(45)
      addLog('[Gemma] Re-scoring session...', 'warning')
      addLog('[Gemma] risk_score=45 — monitoring', 'warning')
    })
    at(4500, () => {
      setPhase(3)
      setRiskScore(72)
      addLog('[Gemma] risk_score=72 ≥ threshold 70!', 'warning')
      addLog('[RiskMiddleware] Step-up triggered', 'danger')
    })
    at(6000, () => {
      setPhase(4)
      setRiskScore(92)
      setSignals(s => ({ ...s, privilege_req: true }))
      addLog('[Gemma] risk_score=92 ≥ threshold 90!', 'danger')
      addLog('[RiskMiddleware] LOCKOUT triggered', 'danger')
    })
    at(7200, () => {
      setPhase(5)
      addLog('[DB] user.is_active = False', 'danger')
      addLog('[Session] All tokens revoked', 'danger')
      addLog('[Response] 403 — account locked', 'danger')
    })

    return () => {
      timers.forEach(clearTimeout)
      timersRef.current = []
    }
  }, [])

  const riskMeta =
    phase >= 4 ? { label: 'CRITICAL', color: 'var(--danger)' }
      : phase === 3 ? { label: 'STEP-UP', color: 'var(--warning)' }
        : phase === 2 ? { label: 'ELEVATED', color: 'var(--warning)' }
          : { label: 'MONITORING', color: 'var(--success)' }

  const gemmaCls = phase >= 4 ? 'critical' : phase >= 2 ? 'elevated' : ''
  const gemmaText =
    phase >= 4
      ? `{"risk_score": 92,
 "reason": "Multiple critical signals.
 Privilege escalation attempt.
 Account lockout required."}`
      : phase === 3
        ? `{"risk_score": 72,
 "reason": "IP change + high request rate.
 Step-up required."}`
        : phase === 2
          ? `{"risk_score": 45,
 "reason": "Elevated request rate. Monitoring."}`
          : '{"risk_score": 18, "reason": "Nominal"}'

  const sigItems = [
    { key: 'face_similarity', val: '0.94',                       anomalous: false },
    { key: 'ip_changed',      val: phase >= 1 ? 'TRUE' : 'false', anomalous: phase >= 1 },
    { key: 'actions/min',     val: phase >= 1 ? '18.4' : '1.2',   anomalous: phase >= 1 },
    { key: 'failed_attempts', val: phase >= 1 ? '2' : '0',        anomalous: phase >= 1 },
    { key: 'privilege_req',   val: phase >= 4 ? 'TRUE' : 'false', anomalous: phase >= 4 },
  ]

  const timeline = [
    { label: 'Baseline established',            done: true },
    { label: 'IP shift injected',               done: phase >= 1 },
    { label: 'Gemma rescored (45)',             done: phase >= 2 },
    { label: 'Step-up threshold crossed (72)',  done: phase >= 3 },
    { label: 'Lockout threshold crossed (92)',  done: phase >= 4 },
    { label: 'Account locked',                  done: phase >= 5 },
  ]
  const firstPending = timeline.findIndex(t => !t.done)

  return (
    <div className="demo-page">
      <nav className="demo-nav">
        <span className="logo">🔐 AIRGAPPED ZTA</span>
        <span className="breadcrumb">Attack Simulation</span>
        <span className="step-indicator">
          {[0, 1, 2, 3, 4, 5].map(i => (
            <span
              key={i}
              className={'step' + (i < 3 ? ' done' : i === 3 ? ' active' : '')}
            />
          ))}
        </span>
      </nav>

      <div className="demo-body">
        <div className="demo-two-col">

          {/* LEFT — signal monitor + timeline */}
          <div>
            <div className="demo-panel">
              <h2>Injected Signals</h2>
              <div className="signal-grid">
                {sigItems.map(s => (
                  <div
                    key={s.key}
                    className={'signal-item' + (s.anomalous ? ' anomalous' : '')}
                  >
                    <span className="signal-key">{s.key}</span>
                    <span className={'signal-val ' + (s.anomalous ? 'red' : 'green')}>
                      {s.val}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div className="demo-panel" style={{ marginTop: '1.5rem' }}>
              <h2>Timeline</h2>
              <div className="timeline">
                {timeline.map((item, i) => {
                  const state = item.done
                    ? 'done'
                    : i === firstPending ? 'active' : 'future'
                  return (
                    <div key={item.label} className={'tl-item ' + state}>
                      <span className="tl-dot" />
                      {item.label}
                    </div>
                  )
                })}
              </div>
            </div>
          </div>

          {/* RIGHT — risk engine response */}
          <div>
            <div className="demo-panel">
              <h2>Risk Engine Response</h2>
              <div className="risk-wrap">
                <div className="risk-score-number" style={{ color: riskMeta.color }}>
                  {riskScore}
                </div>
                <div className="risk-label" style={{ color: riskMeta.color }}>
                  {riskMeta.label}
                </div>
                <div className="risk-bar-track">
                  <div
                    className="risk-bar-fill"
                    style={{ width: `${riskScore}%`, background: riskMeta.color }}
                  />
                </div>
              </div>

              <div
                className={'gemma-box' + (gemmaCls ? ' ' + gemmaCls : '')}
                style={{ marginTop: '1rem' }}
              >
                {gemmaText}
              </div>

              {phase >= 3 && phase < 5 && (
                <div className="status-banner warning pulse">
                  <div className="banner-title">⚠️ STEP-UP REQUIRED</div>
                  <div className="banner-sub">Session terminated — re-verify identity</div>
                </div>
              )}
              {phase >= 5 && (
                <div className="status-banner danger">
                  <div className="banner-title">🔒 ACCOUNT LOCKED</div>
                  <div className="banner-sub">Administrator action required</div>
                </div>
              )}
            </div>
          </div>

        </div>

        {/* full-width log */}
        <div className="demo-panel" style={{ marginTop: '1.5rem' }}>
          <h2>System Log</h2>
          <div className="terminal-log log-bounded">
            {logLines.map(line => (
              <div key={line.id} className={'log-line ' + line.type}>
                <span className="log-time">{line.time}</span>
                {line.text}
              </div>
            ))}
          </div>
        </div>

        {phase >= 5 && (
          <div className="btn-row">
            <button className="demo-btn" onClick={() => window.open('/demo/admin', '_blank')}>
              👑 View Admin Panel ↗
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
