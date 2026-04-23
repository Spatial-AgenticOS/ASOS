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
        // Measured on 2026.4.27: stmts 25.39 / branches 17.34 /
        // functions 19.01 / lines 27.06. Thresholds live one point
        // below each so a single-comment edit doesn't break CI. Ratchet
        // plan: `docs/coverage.md`. Never lower without a commit-message
        // justification.
        statements: 24,
        branches: 17,
        functions: 18,
        lines: 26,
      },
    },
  },
});
