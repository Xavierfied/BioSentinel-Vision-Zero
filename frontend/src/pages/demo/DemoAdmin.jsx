import { useState, useEffect } from 'react'
import './demo.css'

function riskClass(r) {
  if (r === null || r === undefined) return ''
  if (r >= 90) return 'risk-high'
  if (r >= 70) return 'risk-mid'
  return 'risk-low'
}

export default function DemoAdmin() {
  const [users, setUsers] = useState([
    { id: 1, username: 'testuser',  role: 'user',  active: true,  loginTime: '08:32', risk: 22 },
    { id: 2, username: 'admin',     role: 'admin', active: true,  loginTime: '08:15', risk: 8 },
    { id: 6, username: 'demo_user', role: 'user',  active: false, loginTime: '09:14', risk: 92 },
  ])

  const [unlocking, setUnlocking] = useState(null)
  const [unlockedId, setUnlockedId] = useState(null)
  const [auditRows, setAuditRows] = useState([
    { id: 92, user: 'demo_user', action: 'POST /heartbeat', risk: 92,   meta: '{"status_code":403}' },
    { id: 91, user: 'demo_user', action: 'admin_unblock',   risk: null, meta: '{"unblocked_by":"admin"}' },
    { id: 90, user: 'demo_user', action: 'login_failed',    risk: null, meta: '{"reason":"face mismatch"}' },
    { id: 89, user: 'demo_user', action: 'login_success',   risk: null, meta: '{"similarity":0.94}' },
    { id: 88, user: 'demo_user', action: 'POST /heartbeat', risk: 72,   meta: '{"status_code":401}' },
    { id: 87, user: 'demo_user', action: 'POST /heartbeat', risk: 45,   meta: '{"status_code":200}' },
    { id: 86, user: 'demo_user', action: 'POST /heartbeat', risk: 18,   meta: '{"status_code":200}' },
    { id: 85, user: 'demo_user', action: 'enroll',          risk: null, meta: '{"status":"success"}' },
  ])

  const [now, setNow] = useState(() => new Date().toLocaleTimeString())

  // live clock in the header
  useEffect(() => {
    const iv = setInterval(() => setNow(new Date().toLocaleTimeString()), 1000)
    return () => clearInterval(iv)
  }, [])

  async function handleUnblock(userId) {
    setUnlocking(userId)
    await new Promise(r => setTimeout(r, 1200))
    setUsers(us => us.map(u => (u.id === userId ? { ...u, active: true } : u)))
    setUnlockedId(userId)
    setUnlocking(null)
    setAuditRows(rows => [{
      id: rows[0].id + 1,
      user: 'demo_user',
      action: 'admin_unblock',
      risk: null,
      meta: '{"unblocked_by":"admin"}',
    }, ...rows])
  }

  return (
    <div className="demo-page">
      <header className="admin-header">
        <span className="admin-title">🔐 AirGapped ZTA — Admin Panel</span>
        <span className="admin-meta">
          Logged in as: admin&nbsp;·&nbsp;<span className="admin-clock">{now}</span>
        </span>
      </header>

      <div className="demo-body" style={{ maxWidth: '1000px' }}>

        {/* ---- User Management ---- */}
        <div className="demo-panel">
          <h2>User Management</h2>
          <table className="admin-table admin-users">
            <thead>
              <tr>
                <th>ID</th>
                <th>Username</th>
                <th>Role</th>
                <th>Status</th>
                <th>Last Login</th>
                <th>Risk Score</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id}>
                  <td>{u.id}</td>
                  <td>{u.username}</td>
                  <td>{u.role}</td>
                  <td>
                    {u.active
                      ? <span className="status-pill active">🟢 Active</span>
                      : <span className="status-pill locked">🔴 Locked</span>}
                  </td>
                  <td>{u.loginTime}</td>
                  <td className={riskClass(u.risk)}>{u.risk}</td>
                  <td>
                    {unlocking === u.id ? (
                      <span className="unlocking-text">
                        <span className="spinner" />Unlocking...
                      </span>
                    ) : unlockedId === u.id ? (
                      <span className="unblocked-text">✅ Unblocked</span>
                    ) : !u.active ? (
                      <button className="unblock-btn" onClick={() => handleUnblock(u.id)}>
                        Unblock
                      </button>
                    ) : (
                      <span className="muted-cell">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* ---- Recent AuditLog ---- */}
        <div className="demo-panel" style={{ marginTop: '1.5rem' }}>
          <h2>Recent AuditLog (last 8 entries)</h2>
          <table className="admin-table admin-audit">
            <thead>
              <tr>
                <th>ID</th>
                <th>User</th>
                <th>Action</th>
                <th>Risk Score</th>
                <th>Meta</th>
              </tr>
            </thead>
            <tbody>
              {auditRows.map(row => {
                const rowCls = row.action === 'admin_unblock'
                  ? 'audit-unblock'
                  : (row.risk !== null && row.risk >= 90) ? 'audit-critical' : ''
                return (
                  <tr key={row.id} className={rowCls}>
                    <td>{row.id}</td>
                    <td>{row.user}</td>
                    <td className="mono">{row.action}</td>
                    <td className={riskClass(row.risk)}>
                      {row.risk === null ? '—' : row.risk}
                    </td>
                    <td className="meta-cell">{row.meta}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        <div className="admin-footer">
          AirGapped ZTA v1.0 — All inference local — No cloud dependencies
        </div>
      </div>
    </div>
  )
}
