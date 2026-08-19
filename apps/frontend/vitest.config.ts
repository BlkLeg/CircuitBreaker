import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    pool: 'forks',
    maxConcurrency: 3,
    setupFiles: './src/__tests__/setup.js',
    // e2e/ holds Playwright specs. Vitest's default include pattern matches
    // *.spec.ts too, so without this it tries to run them and fails on
    // "Playwright Test needs to be invoked via 'npx playwright test'".
    exclude: ['**/node_modules/**', '**/dist/**', 'e2e/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
    },
  },
});
