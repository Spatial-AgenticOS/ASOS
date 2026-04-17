import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  use: { baseURL: 'http://localhost:9090' },
  webServer: {
    command: 'cd ../feral-core && python -m uvicorn api.server:app --port 9090',
    url: 'http://localhost:9090/health',
    reuseExistingServer: true,
    timeout: 120000,
  },
});
