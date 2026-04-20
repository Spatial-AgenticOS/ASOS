import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test-setup.js',
    // Playwright E2E specs live in e2e/ and are driven by @playwright/test,
    // not vitest. Excluding them keeps `npm run test` focused on unit +
    // component tests so CI doesn't try to import a playwright test module.
    exclude: ['node_modules/**', 'dist/**', 'e2e/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      // Thresholds are REAL gates, not aspirations. As of the vitest
      // 4.1 bump in 2026.4.17 the actual numbers are ~28/20/25/30
      // (statements/branches/functions/lines). vitest 4 counts branches
      // more strictly than vitest 2 did — the old 54% branch number
      // dropped to ~20% on the same test suite purely because of the
      // counting change, not a regression in coverage.
      //
      // Rule: when a new page, hook, or lib file is added, ship a matching
      // smoke test in the same PR. If the new file drops total statements
      // below 20%, either (a) write more tests, or (b) explicitly raise
      // this ceiling with justification in the commit message.
      thresholds: {
        statements: 20,
        branches: 18,
        functions: 18,
        lines: 20,
      },
    },
  },
})
