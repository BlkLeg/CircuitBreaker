import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.API_TARGET || 'http://localhost:8000'

  return {
    plugins: [react()],
    optimizeDeps: {
      include: ['react-markdown', 'style-to-js'],
    },
    server: {
      proxy: {
        '/api': apiTarget,
        '/user-icons': apiTarget,
        '/branding': apiTarget,
        '/uploads': apiTarget,
      },
    },
  }
})
