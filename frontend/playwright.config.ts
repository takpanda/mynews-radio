import { defineConfig, devices } from '@playwright/test'

const baseURL = 'http://127.0.0.1:3310'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL,
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], browserName: 'chromium' },
    },
  ],
  webServer: [
    {
      command: 'node e2e/mock-api.cjs',
      url: 'http://127.0.0.1:8311/__health',
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      command: 'API_BASE=http://127.0.0.1:8311 ./node_modules/.bin/next dev -H 127.0.0.1 -p 3310',
      url: baseURL,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
})
