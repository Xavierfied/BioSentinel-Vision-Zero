# Demo Showcase — Build Log

This file documents every change made to the frontend in this conversation thread.

---

## Step 1 — Scaffold /demo route

**Files created:**
- `src/pages/DemoShowcase.jsx` — placeholder component (`export default function DemoShowcase() { return <div>Demo loading...</div> }`)
- `src/pages/DemoShowcase.css` — empty file

**Files modified:**
- `src/App.jsx`
  - Added import: `import DemoShowcase from './pages/DemoShowcase'`
  - Added route inside `<Routes>`: `<Route path="/demo" element={<DemoShowcase />} />`
  - Route is NOT wrapped in `<ProtectedRoute>` — accessible without a JWT

---

## Step 2 — Build full DemoShowcase component

Replaced both `DemoShowcase.jsx` and `DemoShowcase.css` completely.

### DemoShowcase.jsx — architecture

**Layout:** Full-viewport 3-column grid (35% / 40% / 25%) + fixed bottom controller bar.

**State machine:** `const SCENES = { 0:'idle', 1:'enrollment', 2:'login', 3:'session', 4:'attack', 5:'lockout' }`  
Keyboard keys `1`–`5` jump to that scene; `0` returns to idle; backtick `` ` `` toggles the controller bar visibility.

**Refs:**
- `videoRef` — live `<video>` element
- `canvasRef` — `<canvas>` overlay (left empty at this step, wired in Step 3)
- `timersRef` — array of every `setTimeout`/`setInterval` id for the active scene
- `logIdRef` — monotonic id counter for log entries
- `riskRef` — mirrors `riskScore` so the rAF tween always reads the correct start value
- `riskRafRef` — `requestAnimationFrame` handle for risk gauge tweening

**useEffects (at this step):**
1. `getUserMedia` webcam stream — starts once on mount, tears down stream on unmount (`deps: []`)
2. Keyboard handler — listens for `keydown`, cleans up on unmount (`deps: []`)
3. Scene driver — clears all timers, resets shared state, runs the active scene's timeline (`deps: [scene]`)

**Scene timelines:**

| Scene | Key behaviour |
|-------|--------------|
| 0 Idle | Large "AirGapped ZTA" title, no risk gauge |
| 1 Enrollment | Types `demo_user` (80ms/char, starts 500ms after load), then `demo@ztasystem.local`; success box appears 2s after typing ends; 5 staggered log lines |
| 2 Login | Two-factor panel; liveness dots animate 1→2→3 at 600ms intervals; JWT panel slides in at +3.3s; 6 staggered log lines |
| 3 Session | Risk score fixed at 18 (green); 2×4 signal grid; Gemma JSON box; 6 staggered log lines |
| 4 Attack | Auto-sequence: t=0 ip_changed→TRUE (red), t=1200ms risk tweens to 45, t=2400ms tweens to 72 + Gemma updates, t=3600ms red alert banner; 8 log lines |
| 5 Lockout | Auto-sequence: t=0 risk=92 (red), t=1000ms lock banner, t=2000ms admin table appears, t=3500ms Unblock button pulses, t=4500ms auto-click simulated, t=5000ms row flips to Active + success box; 8 log lines |

**Risk gauge:** `requestAnimationFrame` tween between values; colour transitions green→amber→red at thresholds 70/90; horizontal fill bar mirrors the number.

**Log panel:** Newest-first, max 20 lines, `slideIn` 150ms animation per entry. Colour coding: lines containing `LOCK`/`revok`/🔒 → red (excluding `unblock`); `WARN`/`risk_score=7`/⚠️ → amber; `PASS`/`success`/✅ → green; else default terminal green.

**Timer discipline:** Every `setTimeout` and `setInterval` id is pushed into `timersRef`. The scene-driver `useEffect` cleanup calls `clearTimers()` so animations never bleed between scenes.

### DemoShowcase.css — key classes

| Class | Purpose |
|-------|---------|
| `.demo-page` | `100vh` grid, 3 columns, `padding-bottom: 3rem` for controller bar |
| `.demo-col` | Flex column, `gap: 0.8rem`, `min-height: 0` |
| `.demo-panel` | `bg-panel`, border, `border-radius: 10px` |
| `.demo-panel--fill` | `flex: 1`, `min-height: 0` — stretches to fill column |
| `.webcam-wrapper` | Relative container, `aspect-ratio: 4/3`, video + canvas absolutely stacked, both `scaleX(-1)` mirrored |
| `.terminal-log` | `#050510` background, monospace, green text, `overflow-y: auto` |
| `.log-line` | `slideIn` 150ms animation, colour variants `.green`/`.amber`/`.red` |
| `.risk-score-number` | `4rem`, `font-weight: 800`, `transition: color 0.5s` |
| `.risk-bar-fill` | `transition: width 0.8s, background 0.5s` |
| `.status-banner` | Variants `.safe` / `.warning` / `.danger` |
| `.controller-bar` | `position: fixed`, bottom 0, `transition: opacity 0.3s`; `.hidden` sets `opacity: 0; pointer-events: none` |
| `.scene-btn` | `.active` highlights with `--accent` |
| `.unblock-btn` | `.pulse` applies CSS `@keyframes pulse` box-shadow ring |
| `.typing-cursor` | 2px inline-block, `@keyframes blink` 1s infinite |
| `@keyframes slideIn` | `translateY(-8px) opacity:0` → `translateY(0) opacity:1` |
| `@keyframes pulse` | Box-shadow ring expands and fades |

All colours use CSS variables from `src/styles/global.css`: `--bg-base`, `--bg-panel`, `--bg-input`, `--accent`, `--accent-lt`, `--success`, `--warning`, `--danger`, `--text`, `--text-muted`, `--border`.

**Verified:** `npx vite build` — 35 modules transformed, build succeeded in ~382ms.

---

## Step 3 — Add MediaPipe face mesh overlay

**Files modified:**
- `src/pages/DemoShowcase.jsx` only — two surgical edits, no existing logic changed.

**Changes:**

1. Added `cameraRef = useRef(null)` alongside existing refs (stores the MediaPipe `Camera` instance for cleanup).

2. Added a new `useEffect` (deps `[]`, runs once after mount) between the `getUserMedia` effect and the keyboard effect:

```js
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
    // resize canvas to video dimensions each frame
    // draw video frame
    // if landmarks: draw FACEMESH_TESSELATION (#1a1a3a, 0.5px)
    //               draw FACEMESH_FACE_OVAL   (#6c63ff, 2px)
  })

  const cam = new window.Camera(videoRef.current, {
    onFrame: async () => { await faceMesh.send({ image: videoRef.current }) },
    width: 640, height: 480,
  })
  cam.start()
  cameraRef.current = cam

  return () => { cam.stop(); faceMesh.close() }
}, [])
```

Guards: returns early if `window.FaceMesh`, `window.Camera`, or `videoRef.current` are not available (MediaPipe loaded from CDN as globals in `index.html`).

**Final useEffect order in the file:**
1. Line 165 — `getUserMedia` stream (`deps: []`)
2. Line 174 — FaceMesh overlay (`deps: []`) ← added in this step
3. Line 228 — keyboard handler (`deps: []`)
4. Line 239 — scene driver (`deps: [scene]`)

---

## File inventory after all steps

```
frontend/
  src/
    App.jsx                          — /demo route added
    pages/
      DemoShowcase.jsx               — full scripted demo component
      DemoShowcase.css               — all styles for the demo page
  demo.md                            — this file
```
