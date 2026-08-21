import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // 本地开发走代理：前端 5173 → /api → 后端 8000，同源无 CORS
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
