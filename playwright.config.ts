// Playwright Test setup (added by QA for EA-13). The specs run against an already running stack:
//   npm run up && npm run seed && npx playwright test
// Base URLs come from the environment: ADMIN_URL overrides the admin URL, else it follows ADMIN_PORT
// (shell, then .env, default 3000) exactly like compose.yaml.
import { defineConfig, devices } from "@playwright/test";
import { adminUrl } from "./scripts/lib/admin-url.mjs";

const ADMIN_URL = adminUrl(import.meta.dirname, process.env);

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
