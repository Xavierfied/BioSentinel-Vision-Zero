// enroll.js — AirGapped ZTA biometric enrollment
// Vanilla JS, no frameworks, no classes. Drives a MediaPipe FaceMesh
// liveness challenge in the browser, captures a confirmed frame, then
// POSTs it to the backend /enroll/ endpoint.

const API_BASE = "http://127.0.0.1:8000";
const CHALLENGES = ["blink", "turn_left", "turn_right"];
const CHALLENGE_INSTRUCTIONS = {
  blink:      "👁  Please blink both eyes fully",
  turn_left:  "⬅️  Please turn your head to the LEFT",
  turn_right: "➡️  Please turn your head to the RIGHT"
};
const EAR_THRESHOLD = 0.20;
const TURN_LEFT_THRESHOLD = 0.65;
const TURN_RIGHT_THRESHOLD = 0.35;
const CONFIRM_FRAMES = 3;

// MediaPipe landmark indices (must match backend)
const LEFT_EYE  = [33, 160, 158, 133, 153, 144];
const RIGHT_EYE = [362, 385, 387, 263, 373, 380];
const NOSE_TIP  = 1;
const L_CHEEK   = 234;
const R_CHEEK   = 454;

// --- State -----------------------------------------------------------------
let currentChallenge = null;
let consecutiveFrames = 0;
let capturedBlob = null;
let capturedDataUrl = null;
let faceMesh = null;
let camera = null;

// --- DOM references (assigned in init) -------------------------------------
let video, overlay, ctx, challengeText, statusText,
    submitBtn, previewBox, capturedImg, statusMsg, dots;

// 1. Euclidean distance between two normalised landmark points.
function euclidean(p1, p2) {
  return Math.sqrt((p1.x - p2.x) ** 2 + (p1.y - p2.y) ** 2);
}

// 2. Eye aspect ratio from 6 landmark indices.
function eyeAspectRatio(landmarks, indices) {
  const pts = indices.map(i => landmarks[i]);
  const v1 = euclidean(pts[1], pts[5]);
  const v2 = euclidean(pts[2], pts[4]);
  const h  = euclidean(pts[0], pts[3]);
  if (h === 0) return 0;
  return (v1 + v2) / (2 * h);
}

// 3. Decide whether the current challenge is satisfied this frame.
function detectChallenge(landmarks) {
  if (currentChallenge === "blink") {
    const leftEar  = eyeAspectRatio(landmarks, LEFT_EYE);
    const rightEar = eyeAspectRatio(landmarks, RIGHT_EYE);
    const avgEar   = (leftEar + rightEar) / 2;
    return avgEar < EAR_THRESHOLD;
  }

  if (currentChallenge === "turn_left") {
    const noseX = landmarks[NOSE_TIP].x;
    const lchX  = landmarks[L_CHEEK].x;
    const rchX  = landmarks[R_CHEEK].x;
    const faceW = Math.abs(rchX - lchX);
    if (faceW === 0) return false;
    const offset = (noseX - lchX) / faceW;
    return offset > TURN_LEFT_THRESHOLD;
  }

  if (currentChallenge === "turn_right") {
    const noseX = landmarks[NOSE_TIP].x;
    const lchX  = landmarks[L_CHEEK].x;
    const rchX  = landmarks[R_CHEEK].x;
    const faceW = Math.abs(rchX - lchX);
    if (faceW === 0) return false;
    const offset = (noseX - lchX) / faceW;
    return offset < TURN_RIGHT_THRESHOLD;
  }

  return false;
}

// 4. Reflect challenge progress onto the three progress dots.
function updateDots(count) {
  dots.forEach((d, i) => {
    d.className = 'dot';
    if (i < count) d.classList.add('active');
    if (i < consecutiveFrames && capturedBlob) d.classList.add('done');
  });
}

// 5. Grab the current video frame as a blob + data URL, lock in the capture.
function captureFrame() {
  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const c = canvas.getContext('2d');
  c.drawImage(video, 0, 0, canvas.width, canvas.height);

  capturedDataUrl = canvas.toDataURL('image/jpeg', 0.9);
  canvas.toBlob(blob => {
    capturedBlob = blob;
    capturedImg.src = capturedDataUrl;
    previewBox.style.display = 'block';
    submitBtn.disabled = false;
    challengeText.textContent = '✅ Face captured!';
    statusText.textContent =
      'Ready to enroll — click the button below';
    dots.forEach(d => d.className = 'dot done');
    if (camera) camera.stop();
  }, 'image/jpeg', 0.9);
}

// 6. MediaPipe results callback — runs once per processed frame.
function onResults(results) {
  ctx.clearRect(0, 0, overlay.width, overlay.height);
  ctx.drawImage(results.image, 0, 0, overlay.width, overlay.height);

  if (capturedBlob) return; // already captured, nothing more to do

  if (!results.multiFaceLandmarks || results.multiFaceLandmarks.length === 0) {
    consecutiveFrames = 0;
    statusText.textContent = 'No face detected';
    updateDots(0);
    return;
  }

  const landmarks = results.multiFaceLandmarks[0];

  drawConnectors(ctx, landmarks, FACEMESH_TESSELATION,
    { color: '#2a2a4a', lineWidth: 0.5 });
  drawConnectors(ctx, landmarks, FACEMESH_FACE_OVAL,
    { color: '#6c63ff', lineWidth: 1.5 });

  const detected = detectChallenge(landmarks);
  if (detected) {
    consecutiveFrames++;
    statusText.textContent = `Hold it... ${consecutiveFrames}/${CONFIRM_FRAMES}`;
    updateDots(consecutiveFrames);
    if (consecutiveFrames >= CONFIRM_FRAMES) {
      captureFrame();
    }
  } else {
    consecutiveFrames = 0;
    statusText.textContent = 'Keep trying...';
    updateDots(0);
  }
}

// 7. Pick a challenge, spin up FaceMesh + the camera utility.
async function initCamera() {
  currentChallenge = CHALLENGES[Math.floor(Math.random() * CHALLENGES.length)];
  challengeText.textContent = CHALLENGE_INSTRUCTIONS[currentChallenge];
  statusText.textContent = 'Position your face';

  faceMesh = new FaceMesh({
    locateFile: f =>
      `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh@0.4/${f}`
  });
  faceMesh.setOptions({
    maxNumFaces: 1,
    refineLandmarks: false,
    minDetectionConfidence: 0.5,
    minTrackingConfidence: 0.5
  });
  faceMesh.onResults(onResults);

  camera = new Camera(video, {
    onFrame: async () => {
      await faceMesh.send({ image: video });
    },
    width: 640,
    height: 480
  });
  camera.start();
}

// 8. Validate the form, package the capture, and POST it to the backend.
async function submitEnrollment() {
  if (!capturedBlob) {
    showStatus('No face captured yet', 'error');
    return;
  }

  const username = document.getElementById('username');
  const email = document.getElementById('email');
  const password = document.getElementById('password');

  if (!username.value.trim() || !email.value.trim() ||
      !password.value || password.value.length < 8) {
    showStatus('Please fill in all fields (password min 8 chars)', 'error');
    return;
  }

  submitBtn.disabled = true;
  submitBtn.textContent = 'Enrolling...';
  showStatus('', '');

  try {
    const formData = new FormData();
    formData.append('username', username.value.trim());
    formData.append('email', email.value.trim());
    formData.append('password', password.value);
    formData.append('challenge_type', currentChallenge);
    formData.append('image', capturedBlob, 'face.jpg');

    const response = await fetch(`${API_BASE}/enroll/`, {
      method: 'POST',
      body: formData
    });

    if (response.ok) {
      showStatus('Enrollment successful! Redirecting...', 'success');
      setTimeout(() => {
        window.location.href = '/static/login.html';
      }, 1500);
    } else {
      const data = await response.json();
      showStatus(data.detail || 'Enrollment failed', 'error');
      submitBtn.disabled = false;
      submitBtn.textContent = 'Complete Enrollment';
    }
  } catch (err) {
    showStatus('Network error', 'error');
    submitBtn.disabled = false;
    submitBtn.textContent = 'Complete Enrollment';
  }
}

// 9. Show / clear the status message banner.
function showStatus(msg, type) {
  statusMsg.textContent = msg;
  statusMsg.className = 'status-msg';
  if (type) statusMsg.classList.add(type);
  statusMsg.style.display = msg ? 'block' : 'none';
}

// 10. Wire up DOM references and kick off the camera.
function init() {
  video = document.getElementById('video');
  overlay = document.getElementById('overlay');
  ctx = overlay.getContext('2d');
  challengeText = document.getElementById('challengeText');
  statusText = document.getElementById('statusText');
  submitBtn = document.getElementById('submitBtn');
  previewBox = document.getElementById('previewBox');
  capturedImg = document.getElementById('capturedImg');
  statusMsg = document.getElementById('statusMsg');
  dots = [
    document.getElementById('dot0'),
    document.getElementById('dot1'),
    document.getElementById('dot2')
  ];

  // Match the overlay canvas to the live video resolution.
  video.addEventListener('loadeddata', () => {
    overlay.width = video.videoWidth;
    overlay.height = video.videoHeight;
  });

  submitBtn.addEventListener('click', submitEnrollment);
  initCamera();
}

document.addEventListener('DOMContentLoaded', init);
