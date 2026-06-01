import { useEffect, useRef, useState, useCallback } from 'react'
import './LivenessCamera.css'

// Challenge config — MUST match backend liveness.py exactly
const CHALLENGES = ['blink', 'turn_left', 'turn_right']
const INSTRUCTIONS = {
  blink:      '👁  Blink both eyes fully',
  turn_left:  '⬅️  Turn your head LEFT',
  turn_right: '➡️  Turn your head RIGHT',
}
const EAR_THRESHOLD        = 0.20
const TURN_LEFT_THRESHOLD  = 0.65
const TURN_RIGHT_THRESHOLD = 0.35
const CONFIRM_FRAMES       = 3

// MediaPipe landmark indices — MUST match backend liveness.py
const LEFT_EYE  = [33, 160, 158, 133, 153, 144]
const RIGHT_EYE = [362, 385, 387, 263, 373, 380]
const NOSE_TIP  = 1
const L_CHEEK   = 234
const R_CHEEK   = 454

function euclidean(a, b) {
  return Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)
}

function eyeAspectRatio(landmarks, indices) {
  const pts = indices.map(i => landmarks[i])
  const v1 = euclidean(pts[1], pts[5])
  const v2 = euclidean(pts[2], pts[4])
  const h  = euclidean(pts[0], pts[3])
  return h === 0 ? 0 : (v1 + v2) / (2 * h)
}

function detectChallenge(landmarks, challenge) {
  if (challenge === 'blink') {
    const ear = (
      eyeAspectRatio(landmarks, LEFT_EYE) +
      eyeAspectRatio(landmarks, RIGHT_EYE)
    ) / 2
    return ear < EAR_THRESHOLD
  }
  const noseX = landmarks[NOSE_TIP].x
  const lchX  = landmarks[L_CHEEK].x
  const rchX  = landmarks[R_CHEEK].x
  const faceW = Math.abs(rchX - lchX)
  if (faceW === 0) return false
  const offset = (noseX - lchX) / faceW
  if (challenge === 'turn_left')  return offset > TURN_LEFT_THRESHOLD
  if (challenge === 'turn_right') return offset < TURN_RIGHT_THRESHOLD
  return false
}

export function pickRandomChallenge() {
  return CHALLENGES[Math.floor(Math.random() * CHALLENGES.length)]
}

export default function LivenessCamera({ onCapture, onError }) {
  const [challenge, setChallenge]     = useState(null)
  const [frames, setFrames]           = useState(0)
  const [captured, setCaptured]       = useState(false)
  const [instruction, setInstruction] = useState('Starting camera...')
  const [statusText, setStatusText]   = useState('Please wait')
  const [capturedUrl, setCapturedUrl] = useState(null)
  const [cameraError, setCameraError] = useState(null)

  const videoRef    = useRef(null)
  const canvasRef   = useRef(null)
  const cameraRef   = useRef(null)
  // Refs mirror state so the MediaPipe onResults callback (a stable
  // closure) always reads current values rather than stale snapshots.
  const capturedRef  = useRef(false)
  const framesRef    = useRef(0)
  const challengeRef = useRef(null)

  const captureFrame = useCallback(() => {
    const video  = videoRef.current
    const canvas = document.createElement('canvas')
    canvas.width  = video.videoWidth  || 640
    canvas.height = video.videoHeight || 480
    canvas.getContext('2d').drawImage(video, 0, 0)
    const dataUrl = canvas.toDataURL('image/jpeg', 0.92)
    canvas.toBlob(blob => {
      setCapturedUrl(dataUrl)
      setCaptured(true)
      capturedRef.current = true
      setInstruction('✅ Face captured!')
      setStatusText('Challenge passed — ready to proceed')
      if (cameraRef.current) cameraRef.current.stop()
      onCapture(blob, dataUrl, challengeRef.current)
    }, 'image/jpeg', 0.92)
  }, [onCapture])

  const onResults = useCallback((results) => {
    const canvas = canvasRef.current
    const video  = videoRef.current
    if (!canvas || !video) return

    const ctx = canvas.getContext('2d')
    canvas.width  = video.videoWidth  || 640
    canvas.height = video.videoHeight || 480
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(results.image, 0, 0, canvas.width, canvas.height)

    if (capturedRef.current) return

    const lmList = results.multiFaceLandmarks
    if (!lmList || lmList.length === 0) {
      framesRef.current = 0
      setFrames(0)
      setStatusText('No face detected — look at camera')
      return
    }

    const landmarks = lmList[0]

    // Draw face mesh overlay using CDN globals
    if (window.drawConnectors && window.FACEMESH_TESSELATION) {
      window.drawConnectors(ctx, landmarks,
        window.FACEMESH_TESSELATION,
        { color: '#2a2a4a', lineWidth: 0.5 })
    }
    if (window.drawConnectors && window.FACEMESH_FACE_OVAL) {
      window.drawConnectors(ctx, landmarks,
        window.FACEMESH_FACE_OVAL,
        { color: '#6c63ff', lineWidth: 1.5 })
    }

    const detected = detectChallenge(landmarks, challengeRef.current)

    if (detected) {
      framesRef.current += 1
      setFrames(framesRef.current)
      setStatusText(`Hold it... ${framesRef.current}/${CONFIRM_FRAMES}`)
      if (framesRef.current >= CONFIRM_FRAMES) {
        captureFrame()
      }
    } else {
      framesRef.current = 0
      setFrames(0)
      setStatusText('Keep trying...')
    }
  }, [captureFrame])

  useEffect(() => {
    // Pick random challenge
    const c = CHALLENGES[Math.floor(Math.random() * CHALLENGES.length)]
    setChallenge(c)
    challengeRef.current = c
    setInstruction(INSTRUCTIONS[c])
    setStatusText('Position your face in the camera')

    // Guard: MediaPipe must be loaded from CDN
    if (!window.FaceMesh || !window.Camera) {
      const msg = 'MediaPipe not loaded. Check CDN scripts.'
      setCameraError(msg)
      onError?.(msg)
      return
    }

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
    faceMesh.onResults(onResults)

    const camera = new window.Camera(videoRef.current, {
      onFrame: async () => {
        await faceMesh.send({ image: videoRef.current })
      },
      width: 640,
      height: 480,
    })

    camera.start()
      .catch(err => {
        const msg = `Camera error: ${err.message}`
        setCameraError(msg)
        onError?.(msg)
      })

    cameraRef.current = camera

    // Cleanup on unmount
    return () => {
      camera.stop()
      faceMesh.close()
    }
  }, [onResults, onError])

  if (cameraError) return (
    <div className="camera-error">
      <p>⚠️ {cameraError}</p>
      <p style={{ fontSize: '0.75rem', marginTop: '0.4rem' }}>
        Check browser camera permissions and try again.
      </p>
    </div>
  )

  return (
    <div>
      <div className="liveness-wrapper">
        <video ref={videoRef} autoPlay playsInline
               muted style={{ transform: 'scaleX(-1)' }} />
        <canvas ref={canvasRef}
                style={{ transform: 'scaleX(-1)' }} />
      </div>

      <div className="challenge-box">
        <div className="challenge-instruction">
          {instruction}
        </div>
        <div className="challenge-status">
          {statusText}
        </div>
        <div className="progress-dots">
          {[0, 1, 2].map(i => (
            <div key={i} className={
              'dot' +
              (captured ? ' done' :
               i < frames ? ' active' : '')
            } />
          ))}
        </div>
      </div>

      <div className={
        'captured-preview' + (captured ? ' visible' : '')}>
        <p className="captured-label">✅ Face captured</p>
        <img src={capturedUrl} alt="Captured face" />
      </div>
    </div>
  )
}
