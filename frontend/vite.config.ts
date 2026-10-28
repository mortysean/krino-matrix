import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The backend runs on :8000 (uvicorn backend.main:app); in dev every /api call is proxied to it
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
