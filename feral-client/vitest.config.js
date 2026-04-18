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
      // Thresholds are REAL gates, not aspirations. As of the smoke-test
      // batch in v2026.4.14 the actual numbers are ~28/54/22/28; we leave
      // a small safety margin so individual file changes don't regress
      // the gate.
      //
      // Rule: when a new page, hook, or lib file is added, ship a matching
      // smoke test in the same PR. If the new file drops total statements
      // below 20%, either (a) write more tests, or (b) explicitly raise
      // this ceiling with justification in the commit message.
      thresholds: {
        statements: 20,
        branches: 40,
        functions: 18,
        lines: 20,
      },
    },
  },
})
