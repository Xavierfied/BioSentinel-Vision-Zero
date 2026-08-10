import { useNavigate } from 'react-router-dom'
import './demo.css'

const BADGES = [
  { icon: '🔒', title: 'Air-Gapped',    sub: 'No cloud APIs' },
  { icon: '🧠', title: 'Local AI',      sub: 'Gemma via LM Studio' },
  { icon: '👁', title: 'Biometric 2FA', sub: 'YOLOv8 + DeepFace' },
]

const FLOW = ['Enroll', 'Login', 'Session', 'Monitor', 'Admin']

export default function DemoLanding() {
  const navigate = useNavigate()

  return (
    <div className="demo-page">
      <nav className="demo-nav">
        <span className="logo">🔐 AIRGAPPED ZTA</span>
        <span className="breadcrumb">System Overview</span>
        <span className="step-indicator">
          {[0, 1, 2, 3, 4, 5].map(i => (
            <span key={i} className="step" />
          ))}
        </span>
      </nav>

      <div className="demo-hero">
        <h1 className="hero-title">AirGapped Zero-Trust</h1>
        <p className="hero-subtitle">Biometric Authentication System</p>

        <div className="badge-row">
          {BADGES.map(b => (
            <div key={b.title} className="badge">
              <div className="badge-icon">{b.icon}</div>
              <div className="badge-title">{b.title}</div>
              <div className="badge-sub">{b.sub}</div>
            </div>
          ))}
        </div>

        <div className="flow-row">
          {FLOW.map((f, i) => (
            <span key={f} style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
              <span className="flow-box">{f}</span>
              {i < FLOW.length - 1 && <span className="flow-arrow">→</span>}
            </span>
          ))}
        </div>

        <button className="demo-btn" onClick={() => navigate('/demo/enroll')}>
          Begin Demo →
        </button>
      </div>
    </div>
  )
}
