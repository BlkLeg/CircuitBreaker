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
      rollupOptions: {
        output: {
          // Split large third-party libraries into separate hashed chunks.
          // Each chunk is cached independently so an app code change does not
          // bust the elkjs/reactflow download, which rarely changes.
          manualChunks: {
            'vendor-react':  ['react', 'react-dom', 'react-router-dom'],
            'vendor-flow':   ['reactflow', '@dagrejs/dagre', 'elkjs'],
            'vendor-editor': ['@uiw/react-md-editor', 'react-markdown', 'react-syntax-highlighter'],
            'vendor-ui':     ['lucide-react', '@emoji-mart/react', '@emoji-mart/data'],
          },
        },
      },
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
