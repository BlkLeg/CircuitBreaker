import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { sentryVitePlugin } from '@sentry/vite-plugin'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.API_TARGET || 'http://localhost:8000'

  return {
    plugins: [
      react(),
      // Uploads source maps to Sentry and strips them from the public bundle.
      // SENTRY_AUTH_TOKEN must be set in the build environment; if absent the
      // plugin is a no-op so local dev builds still work without a token.
      sentryVitePlugin({
        org: process.env.SENTRY_ORG,
        project: process.env.SENTRY_PROJECT,
        authToken: process.env.SENTRY_AUTH_TOKEN,
        silent: !process.env.SENTRY_AUTH_TOKEN,
      }),
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
