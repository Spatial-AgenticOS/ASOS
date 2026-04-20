import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Initial v2 coverage gate is intentionally low — the scaffold is small and
// every new page/hook/component will ship a matching smoke test per the
// systematic-sync non-negotiable in AGENT_PROMPT.md. Raise these numbers as
// the suite grows; never lower them without a commit-message justification.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test-setup.js',
    exclude: ['node_modules/**', 'dist/**', 'e2e/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      thresholds: {
        statements: 0,
        branches: 0,
        functions: 0,
        lines: 0,
      },
    },
  },
});
