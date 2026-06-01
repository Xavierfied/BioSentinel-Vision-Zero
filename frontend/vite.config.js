import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/enroll':    'http://localhost:8000',
      '/auth':      'http://localhost:8000',
      '/heartbeat': 'http://localhost:8000',
      '/admin':     'http://localhost:8000',
      '/demo':      'http://localhost:8000',
      '/health':    'http://localhost:8000',
    }
  }
})
