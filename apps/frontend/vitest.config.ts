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
    // 15s, not the 5s default. Under v8 coverage instrumentation the heavier
    // render tests (fleet-table, monitors-dashboard, agent-discovery-scope,
    // agent-assigned-probes) take 5.4-6.9s and intermittently trip the
    // default — a different two or three of them on each run. `npm test` was
    // green because it does not instrument; `npm run test:coverage`, which is
    // what CI runs for the REL-15 gate, was failing roughly every other run on
    // tests that have nothing to do with the change under review.
    testTimeout: 15_000,
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
