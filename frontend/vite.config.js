import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'fs'
import { resolve } from 'path'

// Read the canonical VERSION file from the repo root at build time.
// This value is baked into the JS bundle as import.meta.env.VITE_APP_VERSION.
const APP_VERSION = readFileSync(resolve(__dirname, '../VERSION'), 'utf8').trim()

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.API_TARGET || 'http://localhost:8000'

  return {
    define: {
      // Expose as import.meta.env.VITE_APP_VERSION throughout the app.
      // VITE_APP_VERSION env var (e.g. from CI) overrides the VERSION file.
      'import.meta.env.VITE_APP_VERSION': JSON.stringify(
        env.VITE_APP_VERSION || APP_VERSION
      ),
    },
    plugins: [
      react(),
    ],
    optimizeDeps: {
      include: ['react-markdown', 'style-to-js'],
    },
    build: {
      // Minimum browser floor: these are the first versions to support color-mix(),
      // the most advanced CSS feature used in this app.
      target: ['chrome111', 'firefox113', 'safari16.4', 'edge111'],
      sourcemap: 'hidden',
      assetsInlineLimit: 4096,      // inline assets < 4 KB as base64 (reduces requests)
      chunkSizeWarningLimit: 1000,  // 1 MB threshold (map chunk legitimately exceeds 500 KB)
      commonjsOptions: {
        // elkjs/lib/elk.bundled.js is a browserify bundle that references 'web-worker'
        // as an internal module. Vite's CJS transform tries to resolve it as an external
        // ESM import, which fails at runtime. Ignoring it here causes elkjs to fall back
        // to its built-in non-worker mode, which is correct for browser production builds.
        ignore: ['web-worker'],
      },
      rollupOptions: {
        output: {
          manualChunks: {
            // Core React runtime — downloaded once, browser-cached across all pages
            vendor: ['react', 'react-dom', 'react-router-dom', 'axios'],
            // Heavy graph/topology libs — only fetched when /map is visited
            map: ['reactflow', 'elkjs', '@dagrejs/dagre', '@reactflow/node-resizer'],
            // Markdown editor + syntax highlighting — only needed on /docs
            editor: ['@uiw/react-md-editor', 'react-syntax-highlighter'],
            // Emoji picker — infrequently used; keep isolated
            emoji: ['@emoji-mart/react', '@emoji-mart/data'],
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
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: './src/__tests__/setup.js',
      css: false,
    },
  }
})
