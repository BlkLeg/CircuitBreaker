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
      reporter: ['text', 'json', 'html', 'lcov'],
      reportsDirectory: './coverage',
      exclude: [
        'node_modules/**',
        'dist/**',
        'e2e/**',
        'src/__tests__/**',
        '**/*.config.{js,ts}',
        '**/*.d.ts',
      ],
      // REL-15: a ratchet, not an aspiration. These are the numbers measured on
      // the full suite on 2026-08-18 (stmts 38.84, branch 31.32, funcs 30.99,
      // lines 40.62), rounded down to the integer below each. Raise them
      // deliberately as coverage improves; never lower one to make a red build
      // green — that turns the gate into decoration.
      thresholds: {
        statements: 38,
        branches: 31,
        functions: 30,
        lines: 40,
      },
    },
  },
});
