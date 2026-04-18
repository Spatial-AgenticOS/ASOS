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
      // These thresholds reflect TODAY'S reality, not an aspiration. When a
      // page or hook is added, ship a matching smoke test in the same PR so
      // these numbers stay honest. Target ladder lives in CHANGELOG; raise
      // here in the same commit as the test that earned it.
      thresholds: {
        statements: 8,
        branches: 15,
        functions: 15,
        lines: 8,
      },
    },
  },
})
