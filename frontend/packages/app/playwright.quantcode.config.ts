import { defineConfig, devices } from "@playwright/test"

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:4444"

export default defineConfig({
  testDir: "./e2e/quantcode",
  outputDir: "./e2e/test-results/quantcode",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  workers: 1,
  reporter: [["list"], ["html", { outputFolder: "e2e/quantcode-report", open: "never" }]],
  use: {
    baseURL,
    ...devices["Desktop Chrome"],
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: process.env.PLAYWRIGHT_EXTERNAL_SERVER === "1" ? undefined : {
    command: "bun run --cwd ../.. dev:quantcode",
    url: baseURL,
    reuseExistingServer: true,
    timeout: 120_000,
  },
})
