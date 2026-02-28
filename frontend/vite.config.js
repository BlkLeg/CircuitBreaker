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
    build: {
      // Minimum browser floor: these are the first versions to support color-mix(),
      // the most advanced CSS feature used in this app.
      target: ['chrome111', 'firefox113', 'safari16.4', 'edge111'],
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
