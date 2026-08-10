import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import './demo.css'

const USERNAME = 'demo_user'
const EMAIL    = 'demo@ztasystem.local'

const PIPELINE = [
  { tag: 'YOLOv8',     label: 'Face Detection' },
  { tag: 'RetinaFace', label: 'Step-Up Verification' },
  { tag: 'DeepFace',   label: 'Embedding Extraction' },
  { tag: 'Database',   label: 'Embedding Stored' },
]

export default function DemoEnroll() {
  const navigate = useNavigate()

  const [usernameVal,  setUsernameVal]  = useState('')
  const [emailVal,     setEmailVal]     = useState('')
  const [pwDone,       setPwDone]       = useState(false)
  const [pipelineStep, setPipelineStep] = useState(-1)
  const [enrolled,     setEnrolled]     = useState(false)
  const [cameraReady,  setCameraReady]  = useState(false)
  // which field is mid-type, so only that field shows the blinking cursor
  const [typingField,  setTypingField]  = useState('')

  const videoRef  = useRef(null)
  const canvasRef = useRef(null)
  const cameraRef = useRef(null)
  const streamRef = useRef(null)
  const timersRef = useRef([])

  // ---- scripted enrollment animation (runs once) ----
  useEffect(() => {
    const timers = timersRef.current
    const push = id => { timers.push(id); return id }

    const typeInto = (text, setter, field, onDone) => {
      setTypingField(field)
      let i = 0
      const iv = setInterval(() => {
        i += 1
        setter(text.slice(0, i))
        if (i >= text.length) {
          clearInterval(iv)
          setTypingField('')
          if (onDone) onDone()
        }
      }, 160)
      push(iv)
    }

    // t=600ms — type username, then email, then reveal password + pipeline
    push(setTimeout(() => {
      typeInto(USERNAME, setUsernameVal, 'username', () => {
        typeInto(EMAIL, setEmailVal, 'email', () => {
          setPwDone(true)
          push(setTimeout(() => setPipelineStep(0), 400))
          push(setTimeout(() => setPipelineStep(1), 700))
          push(setTimeout(() => setPipelineStep(2), 1000))
          push(setTimeout(() => setPipelineStep(3), 1300))
          push(setTimeout(() => { setPipelineStep(4); setEnrolled(true) }, 1900))
        })
      })
    }, 1000))

    return () => {
      timers.forEach(id => { clearTimeout(id); clearInterval(id) })
      timersRef.current = []
    }
  }, [])

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

  return (
    <div className="demo-page">
      <nav className="demo-nav">
        <span className="logo">🔐 AIRGAPPED ZTA</span>
        <span className="breadcrumb">Step 1 — Enrollment</span>
        <span className="step-indicator">
          {[0, 1, 2, 3, 4, 5].map(i => (
            <span key={i} className={'step' + (i === 0 ? ' active' : '')} />
          ))}
        </span>
      </nav>

      <div className="demo-body">
        <div className="demo-two-col">

          {/* LEFT — webcam */}
          <div className="demo-panel">
            <h2>Webcam Feed</h2>
            <div className="webcam-wrapper">
              <video ref={videoRef} autoPlay playsInline muted />
              <canvas ref={canvasRef} />
            </div>
            <div className="challenge-pill">
              {enrolled
                ? '✅ Face captured successfully'
                : '👁 Analysing biometrics...'}
            </div>
          </div>

          {/* RIGHT — enrollment pipeline */}
          <div className="demo-panel">
            <h2>Account Details</h2>

            <div className="field-label">Username</div>
            <div className={'demo-field' + (usernameVal === USERNAME ? ' done' : '')}>
              {usernameVal}
              {typingField === 'username' && <span className="type-cursor" />}
            </div>

            <div className="field-label">Email</div>
            <div className={'demo-field' + (emailVal === EMAIL ? ' done' : '')}>
              {emailVal}
              {typingField === 'email' && <span className="type-cursor" />}
            </div>

            <div className="field-label">Password</div>
            <div className={'demo-field' + (pwDone ? ' done' : '')}>
              {pwDone ? '••••••••••' : ''}
            </div>

            <h2 style={{ marginTop: '1.4rem' }}>CV Pipeline</h2>
            <div className="pipeline-steps">
              {PIPELINE.map((p, i) => (
                <div
                  key={p.tag}
                  className={
                    'pipeline-step' +
                    (i < pipelineStep ? ' done'
                      : i === pipelineStep ? ' active' : '')
                  }
                >
                  <span className="label">[{p.tag}]</span>
                  <span>{p.label}</span>
                </div>
              ))}
            </div>

            <div className={'success-box' + (enrolled ? ' visible' : '')}>
              <div className="title">✅ Enrollment Complete</div>
              <div>Face embedding: 128 dimensions (Facenet)</div>
              <div>Similarity threshold: 0.60</div>
              <div>User stored in SQLite</div>
            </div>
          </div>

        </div>

        <div className="btn-row">
          <button
            className="demo-btn"
            onClick={() => navigate('/demo/login')}
            disabled={!enrolled}
          >
            Continue to Login →
          </button>
        </div>
      </div>
    </div>
  )
}
