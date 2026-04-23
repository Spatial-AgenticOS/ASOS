import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// v2 coverage gate. Thresholds are deliberately modest in this commit
// because large chunks of the client talk to the live Brain WebSocket
// and are better exercised with e2e. Ratchet lives in docs/coverage.md.
// Raise these numbers as the suite grows; never lower without a
// justification in the commit message.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test-setup.js',
    exclude: ['node_modules/**', 'dist/**', 'e2e/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov', 'json-summary'],
      include: ['src/**/*.{js,jsx}'],
      exclude: [
        'src/**/__tests__/**',
        'src/**/*.test.{js,jsx}',
        'src/test-setup.js',
        'src/main.jsx',
        'src/bootstrap.js',
        'src/styles/**',
      ],
      thresholds: {
        // Stage 5.3 (Geofences/Webhooks/Wiki/Identity/Skills/SetupWizard/
        // Dashboard/Health/Memory): measured 32.02 / 24.4 / 25.85 /
        // 34.09. Floor = measured − 1 per axis. Ratchet plan in
        // docs/coverage.md.
        statements: 31,
        branches: 24,
        functions: 25,
        lines: 33,
      },
    },
  },
});
