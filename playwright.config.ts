// Playwright Test setup (added by QA for EA-13). The specs run against an already running stack:
//   npm run up && npm run seed && npx playwright test
// Base URLs come from the environment; the defaults are the fixed local URLs of the README.
import { defineConfig, devices } from "@playwright/test";

const ADMIN_URL = process.env.ADMIN_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "e2e",
  outputDir: ".work/playwright-results",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: [["list"], ["html", { outputFolder: ".work/playwright-report", open: "never" }]],
  use: {
    baseURL: ADMIN_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
