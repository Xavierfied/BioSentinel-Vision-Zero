import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// bypass(req) returns the URL to serve locally (skipping the proxy) for any
// non-POST request so React Router can handle SPA navigation to /enroll, etc.
function apiOnly(req) {
  if (req.method !== 'POST') return req.url
}

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/enroll':    { target: 'http://localhost:8000', bypass: apiOnly },
      '/auth':      { target: 'http://localhost:8000', bypass: apiOnly },
      '/heartbeat': { target: 'http://localhost:8000', bypass: apiOnly },
      '/admin':     { target: 'http://localhost:8000', bypass: apiOnly },
      '/demo':      { target: 'http://localhost:8000', bypass: apiOnly },
      '/health':    { target: 'http://localhost:8000', bypass: apiOnly },
    }
  }
})
