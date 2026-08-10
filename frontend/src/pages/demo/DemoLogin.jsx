import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import './demo.css'

const CHALLENGES = ['BLINK BOTH EYES', 'TURN HEAD LEFT', 'TURN HEAD RIGHT']

export default function DemoLogin() {
  const navigate = useNavigate()

  // 0 idle · 1 creds animating · 2 creds done · 3 challenge shown
  // 4 dots filling · 5 liveness passed · 6 comparing · 7 match · 8 jwt
  const [step, setStep] = useState(0)
  const [dots, setDots] = useState(0)
  const [cameraReady, setCameraReady] = useState(false)
  // challenge chosen once on mount
  const [challenge] = useState(() => CHALLENGES[Math.floor(Math.random() * 3)])

  const videoRef  = useRef(null)
  const canvasRef = useRef(null)
  const cameraRef = useRef(null)
  const streamRef = useRef(null)

  // ---- scripted authentication timeline (runs once) ----
  useEffect(() => {
    const timers = []
    const at = (ms, fn) => timers.push(setTimeout(fn, ms))

    at(800,  () => setStep(1))
    at(2200, () => setStep(2))
    at(3000, () => setStep(3))
    at(4000, () => setDots(1))
    at(4600, () => setDots(2))
    at(5200, () => { setDots(3); setStep(4) })
    at(5800, () => setStep(5))
    at(6400, () => setStep(6))
    at(7200, () => setStep(7))
    at(8000, () => setStep(8))
    at(9200, () => navigate('/demo/session'))

    return () => timers.forEach(clearTimeout)
  }, [navigate])

  // ---- live webcam stream ----
  useEffect(() => {
    let cancelled = false
    navigator.mediaDevices.getUserMedia({ video: true })
      .then(s => {
        if (cancelled) { s.getTracks().forEach(t => t.stop()); return }
        streamRef.current = s
        if (videoRef.current) videoRef.current.srcObject = s
        setCameraReady(true)
      })
      .catch(() => {})
    return () => {
      cancelled = true
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(t => t.stop())
        streamRef.current = null
      }
    }
  }, [])

  // ---- MediaPipe face mesh overlay (after camera is live) ----
  useEffect(() => {
    if (!cameraReady) return
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

    return () => { cam.stop(); faceMesh.close() }
  }, [cameraReady])

  const pillText =
    step < 3 ? 'Awaiting credentials...'
      : step < 5 ? `🎯 Challenge: ${challenge}`
        : '✅ Liveness verified'

  return (
    <div className="demo-page">
      <nav className="demo-nav">
        <span className="logo">🔐 AIRGAPPED ZTA</span>
        <span className="breadcrumb">Step 2 — Authentication</span>
        <span className="step-indicator">
          {[0, 1, 2, 3, 4, 5].map(i => (
            <span
              key={i}
              className={'step' + (i === 0 ? ' done' : i === 1 ? ' active' : '')}
            />
          ))}
        </span>
      </nav>

      <div className="demo-body">
        <div className="demo-two-col">

          {/* LEFT — biometric verification */}
          <div className="demo-panel">
            <h2>Biometric Verification</h2>
            <div className="webcam-wrapper">
              <video ref={videoRef} autoPlay playsInline muted />
              <canvas ref={canvasRef} />
            </div>

            <div className="challenge-pill">{pillText}</div>

            {step >= 3 && (
              <div className="progress-dots">
                {[0, 1, 2].map(i => (
                  <div
                    key={i}
                    className={
                      'dot' +
                      (i < dots ? ' done' : i === dots - 1 ? ' active' : '')
                    }
                  />
                ))}
              </div>
            )}

            <div className="liveness-steps">
              <div className={'liveness-step' + (step >= 5 ? ' done' : '')}>
                <span className="icon">{step >= 5 ? '✅' : '○'}</span>
                Neutral position detected
              </div>
              <div className={
                'liveness-step' +
                (step >= 5 ? ' done' : step >= 4 ? ' active' : '')
              }>
                <span className="icon">{step >= 5 ? '✅' : '○'}</span>
                Challenge performed
              </div>
              <div className={'liveness-step' + (step >= 5 ? ' done' : '')}>
                <span className="icon">{step >= 5 ? '✅' : '○'}</span>
                Frame captured
              </div>
            </div>
          </div>

          {/* RIGHT — authentication status */}
          <div className="demo-panel">
            <div className="demo-section">
              <h2>Factor 1: Credentials</h2>
              <div className="demo-subpanel">
                <div className="field-label">Username</div>
                <div className={'demo-field' + (step >= 2 ? ' done' : '')}>
                  demo_user
                </div>
                <div className="field-label">Password</div>
                <div className="demo-field">••••••••••</div>
                {step >= 2 && (
                  <div className="check-item">
                    <span className="ok">✅</span>
                    Password verified — bcrypt PASS
                  </div>
                )}
              </div>
            </div>

            {step >= 3 && (
              <div className="demo-section">
                <h2>Factor 2: Biometric</h2>
                <div className="demo-subpanel">
                  {step >= 5 && (
                    <div className="check-item">
                      <span className="ok">✅</span>
                      Liveness challenge passed
                    </div>
                  )}
                  {step >= 6 && (
                    <div className="check-item">
                      <span className="ok">✅</span>
                      Face detected — conf 0.94
                    </div>
                  )}
                  {step >= 7 && (
                    <div className="check-item">
                      <span className="ok">✅</span>
                      Cosine similarity: 0.94 ≥ 0.60
                    </div>
                  )}
                </div>
              </div>
            )}

            <div className={'jwt-box' + (step >= 8 ? ' visible' : '')}>
              <div className="jwt-label">ACCESS TOKEN</div>
              <div className="jwt-value">
                eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI2IiwidXNlcm5h...
              </div>
              <div className="jwt-label" style={{ marginTop: '0.6rem' }}>ROLE</div>
              <div className="jwt-value">user</div>
              <div className="jwt-label" style={{ marginTop: '0.6rem' }}>EXPIRES</div>
              <div className="jwt-value">30 minutes</div>
            </div>
          </div>

        </div>

        <p className="redirect-note">Authenticating... redirecting to session</p>
      </div>
    </div>
  )
}
