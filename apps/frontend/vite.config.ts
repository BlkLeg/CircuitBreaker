/// <reference types="vite/client" />
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { visualizer } from 'rollup-plugin-visualizer';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// Read the canonical VERSION file from the repo root at build time.
// This value is baked into the JS bundle as import.meta.env.VITE_APP_VERSION.
const ROOT_DIR = fileURLToPath(new URL('../..', import.meta.url));
const APP_VERSION = readFileSync(resolve(ROOT_DIR, 'VERSION'), 'utf8').trim();

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ROOT_DIR, '');
  const apiTarget = env.API_TARGET || 'http://localhost:8000';

  return {
    define: {
      // Expose as import.meta.env.VITE_APP_VERSION throughout the app.
      // VITE_APP_VERSION env var (e.g. from CI) overrides the VERSION file.
      'import.meta.env.VITE_APP_VERSION': JSON.stringify(env.VITE_APP_VERSION || APP_VERSION),
    },
    plugins: [
      react(),
      // Bundle analyzer — only active when ANALYZE=true (e.g. `ANALYZE=true npm run build`).
      // Outputs stats.html in the dist directory for visual bundle inspection.
      process.env.ANALYZE === 'true' &&
        visualizer({
          filename: 'dist/stats.html',
          open: true,
          gzipSize: true,
          brotliSize: true,
          template: 'treemap',
        }),
    ].filter(Boolean),
    optimizeDeps: {
      include: ['react-markdown', 'style-to-js'],
    },
    build: {
      // Browser floor: color-mix() is the most advanced CSS feature used in this app.
      // Broadened from chrome111/ff113 to chrome100/ff100 for wider compatibility,
      // including Chromium builds on Raspberry Pi OS which may lag a few minor versions.
      target: ['chrome100', 'firefox100', 'safari15', 'edge100'],
      sourcemap: 'hidden',
      assetsInlineLimit: 4096, // inline assets < 4 KB as base64 (reduces requests)
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
              const vendorChunkPattern =
                /\/node_modules\/(react|react-dom|react-router|react-router-dom|framer-motion|style-to-js)\//;
              if (vendorChunkPattern.exec(id)) {
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
      host: true,
      allowedHosts: ['localhost', '127.0.0.1', 'circuitbreaker.lab'],
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          ws: true,
        },
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
  };
});
