import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The frontend runs on its own port and proxies every /api call to the backend, so the session cookie stays
// same-origin and no CORS is needed. Both dev and preview read:
//   WEB_PORT    the frontend's port (default 6180); taken strictly, so a busy port fails instead of moving
//   WEB_HOST    the address to listen on (default 127.0.0.1; 0.0.0.0 to reach it from other machines). Not
//               "localhost": on Windows it resolves to ::1 first, which a WSL server on 127.0.0.1 never answers
//   KRINO_API   the backend (default http://127.0.0.1:6181)
const api = process.env.KRINO_API ?? 'http://127.0.0.1:6181'
const web = {
  port: Number(process.env.WEB_PORT ?? 6180),
  host: process.env.WEB_HOST ?? '127.0.0.1',
  strictPort: true,
  proxy: { '/api': api },
}

export default defineConfig({
  plugins: [react()],
  server: web,
  preview: web,
})
