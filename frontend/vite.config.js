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
      // elk.bundled (~1.4 MB, indivisible Java→JS) and DocEditor deps (~1.6 MB,
      // tightly coupled @uiw + react-markdown + react-syntax-highlighter) are both
      // lazy-loaded and cannot be split further without library-level changes.
      chunkSizeWarningLimit: 1700,
      commonjsOptions: {
        // elkjs/lib/elk.bundled.js is a browserify bundle that references 'web-worker'
        // as an internal module. Vite's CJS transform tries to resolve it as an external
        // ESM import, which fails at runtime. Ignoring it here causes elkjs to fall back
        // to its built-in non-worker mode, which is correct for browser production builds.
        ignore: ['web-worker'],
      },
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.includes('node_modules')) {
              // Emoji picker (infrequently used, large ~510 kB) — lazy-loaded on click
              if (id.includes('@emoji-mart')) {
                return 'emoji';
              }
              // Core React runtime
              // framer-motion MUST be here: its UMD bundle references React as a bare global.
              if (
                id.match(/\/node_modules\/(react|react-dom|react-router|react-router-dom|axios|framer-motion|style-to-js)\//)
              ) {
                return 'vendor';
              }
              // All other vendor deps (editor, markdown, syntax-hl) are left for Vite
              // to bundle into lazy async chunks naturally via React.lazy / dynamic import.
              // Splitting @uiw, react-markdown, and react-syntax-highlighter into separate
              // manual chunks causes circular dependency warnings because they import
              // each other internally.
            }
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
