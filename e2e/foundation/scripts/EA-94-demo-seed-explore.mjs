// EA-94 exploratory flow as a script: signs in to the admin UI with every seeded account and the shared
// test password, then prints what each person sees (landing page, sidebar areas, Workspace switcher, role in
// the user menu) and saves one screenshot per account. Read-only: it creates nothing in the database
// except the sign-in sessions every sign-in creates.
//
// Run (stack up and seeded):  node e2e/foundation/scripts/EA-94-demo-seed-explore.mjs [screenshot-dir]
// Environment: ADMIN_URL or ADMIN_PORT (as in playwright.config.ts); EI_AI_SEED_PASSWORD (else .env, else .env.example).
// Sign-ins are paced (about 2 per second) to stay far below the 30 per minute rate limit per IP.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { adminUrl } from "../../../scripts/lib/admin-url.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const ADMIN = adminUrl(ROOT, process.env);
const OUT = process.argv[2] ?? path.join(ROOT, ".work", "EA-94", "screenshots");

const ACCOUNTS = [
  "linh.tran@mekongdevworks.example",
  "minh.pham@mekongdevworks.example",
  "thao.nguyen@mekongdevworks.example",
  "quang.le@mekongdevworks.example",
  "ha.vu@mekongdevworks.example",
  "son.hoang@mekongdevworks.example",
  "duy.lam@mekongdevworks.example",
  "vy.huynh@mekongdevworks.example",
  "phuc.luong@mekongdevworks.example",
  "sysadmin@mekongdevworks.example",
  "ngan.trinh@songhanretail.example",
];

// Reads EI_AI_SEED_PASSWORD from a dotenv-style file.
// Input: file (string). Output: string or undefined.
const dotenvValue = (file) => {
  if (!fs.existsSync(file)) return undefined;
  let found;
  for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
    const match = /^EI_AI_SEED_PASSWORD=(.*)$/.exec(line);
    if (match) found = match[1].trim().replace(/^(["'])(.*)\1$/, "$2");
  }
  return found || undefined;
};

// The shared password the stack was seeded with: shell, then .env, then .env.example.
// Output: string.
const seedPassword = () =>
  process.env.EI_AI_SEED_PASSWORD ||
  dotenvValue(path.join(ROOT, ".env")) ||
  dotenvValue(path.join(ROOT, ".env.example")) ||
  "";

// Signs in through the UI and returns what the person sees on the landing page.
// Input: browser, email, password. Output: Promise<object>.
const exploreAccount = async (browser, email, password) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 860 } });
  const page = await context.newPage();
  const problems = [];
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) problems.push(message.text());
  });
  try {
    await page.goto(`${ADMIN}/sign-in`);
    await page.getByLabel("Work email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForURL(/\/w\/[0-9a-f-]+\/dashboard$/, { timeout: 15000 });
    await page.getByRole("heading", { level: 1, name: "Dashboard" }).waitFor();
    const nav = await page.locator("nav a").allTextContents();
    const buttons = await page.locator("nav button").allTextContents();
    await page.getByTestId("workspace-switcher").click();
    const workspaces = await page.getByRole("menuitemradio").allTextContents();
    fs.mkdirSync(OUT, { recursive: true });
    const shot = path.join(OUT, `explore-${email.split("@")[0]}.png`);
    await page.screenshot({ path: shot });
    return {
      email,
      landed: new URL(page.url()).pathname,
      sidebar: nav.map((text) => text.trim()),
      organizationAndRole: buttons.map((text) => text.trim()),
      workspaceSwitcher: workspaces.map((text) => text.trim()),
      consoleProblems: problems,
    };
  } finally {
    await context.close();
  }
};

// Entry point: explores every account and prints one JSON document.
const main = async () => {
  const password = seedPassword();
  if (!password)
    throw new Error("EI_AI_SEED_PASSWORD is not set in the shell, .env or .env.example");
  const browser = await chromium.launch();
  const results = [];
  try {
    for (const email of ACCOUNTS) {
      results.push(await exploreAccount(browser, email, password));
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify(results, null, 2));
};

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
