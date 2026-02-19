import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    include: ['react-markdown', 'style-to-js'],
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/user-icons': 'http://localhost:8000',
    },
  },
})
