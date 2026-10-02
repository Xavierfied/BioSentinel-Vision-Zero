import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// bypass(req) returns the URL to serve locally (skipping the proxy) for page
// navigations, so React Router can handle /enroll, /login, etc. API calls
// (POSTs, and GETs like /auth/me that ask for JSON) still go to the backend.
function apiOnly(req) {
  const wantsPage = (req.headers.accept || '').includes('text/html')
  if (req.method === 'GET' && wantsPage) return req.url
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
