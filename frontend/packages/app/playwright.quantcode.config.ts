import { defineConfig, devices } from "@playwright/test"

export default defineConfig({
  testDir: "./e2e/quantcode",
  outputDir: "./e2e/test-results/quantcode",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  workers: 1,
  reporter: [["list"], ["html", { outputFolder: "e2e/quantcode-report", open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:4444",
    ...devices["Desktop Chrome"],
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "bun run --cwd ../.. dev:quantcode",
    url: "http://127.0.0.1:4444",
    reuseExistingServer: true,
    timeout: 120_000,
  },
})
