// EA-22 (FND-05): the Workspace shell (Sidebar, switchers, areas, not-found), the sign-in page against the
// design artboards, and the accessibility basics of the auth pages. Black-box specs from
// .work/EA-22/contract.md only. Runs against a running, migrated and seeded stack:
//   npm run up -- --no-model && npm run seed && npm run e2e -- e2e/foundation/EA-22-admin-shell*
// One sign-in through the UI for the whole file (the shared 30/minute budget, see EA-22-admin-sign-in).
import { randomUUID } from "node:crypto";
import path from "node:path";
import { expect, test, type Locator } from "@playwright/test";
import {
  ADMIN,
  ApiSession,
  MSG,
  RUN,
  SCREENSHOTS,
  addMember,
  cleanup,
  contrastRatio,
  createForeignOrg,
  createReadyUser,
  createWorkspace,
  expectDetail,
  expectSameAnswer,
  heightOf,
  inviteUser,
  peopleOpsId,
  signInUi,
  watch,
  withPage,
  withoutExpected401,
  type ForeignOrg,
  type QaUser,
  type StorageState,
} from "../support/ea22";
import { AREAS_BY_PERSONA, visibleNav } from "../support/ea23";

// EA-23 (FND-06): the Sidebar shows only what the role can use. `main` is a Builder in People Ops.
const BUILDER_NAV = visibleNav(AREAS_BY_PERSONA.builder ?? []);
const BUILDER_HIDDEN = ["conversations", "unanswered", "organization"];

const IDENTITY_PARAMS = /[?&](user_?id|org_?id|groups?|tenant)=/i;
const ALPHA_NAME = `QA22 Alpha ${RUN}`;
const ZETA_NAME = `QA22 Zeta ${RUN}`;
const HIDDEN_NAME = `QA22 Hidden ${RUN}`;

test.describe.configure({ mode: "serial", timeout: 240_000 });

let peopleOps = "";
let alpha = "";
let zeta = "";
let hidden = "";
let main: QaUser;
let foreign: ForeignOrg;
let state: StorageState;

function workspaceUrl(workspaceId: string, area = "dashboard"): string {
  return `${ADMIN}/w/${workspaceId}/${area}`;
}

test.beforeAll(async ({ browser }) => {
  cleanup(); // leftovers of a crashed earlier run of this ticket
  peopleOps = peopleOpsId();
  main = await createReadyUser({
    label: "shell",
    role: "builder",
    workspaceId: peopleOps,
    name: `Trần Thị Mai ${RUN}`,
  });
  // People Ops is the first membership (the default); Zeta and Alpha follow in this order.
  zeta = createWorkspace(ZETA_NAME);
  addMember(zeta, main, "workspace_admin");
  alpha = createWorkspace(ALPHA_NAME);
  addMember(alpha, main, "viewer");
  hidden = createWorkspace(HIDDEN_NAME); // `main` is not a member of it
  foreign = createForeignOrg();
  state = await withPage(browser, undefined, async (page, context) => {
    await signInUi(page, main.email, main.password);
    await expect(page).toHaveURL(workspaceUrl(peopleOps));
    return context.storageState();
  });
});

test.afterAll(() => {
  cleanup();
});

// ---------------------------------------------------------------------------------------------
// AC6 navigation
// ---------------------------------------------------------------------------------------------

test("AC6: the workspace is switched from the Sidebar, the URL carries the id and the area is kept", async ({
  browser,
}) => {
  await withPage(browser, state, async (page) => {
    const seen = watch(page);
    await page.goto(`/w/${peopleOps}/dashboard`);
    const switcher = page.getByTestId("workspace-switcher");
    await expect(switcher).toContainText("Workspace");
    await expect(switcher).toContainText("People Ops");
    const userMenu = page.getByTestId("user-menu");
    await expect(userMenu).toContainText(main.name);
    await expect(userMenu).toContainText("Builder");

    await switcher.click();
    const menu = page.getByRole("menu");
    const items = menu.getByRole("menuitemradio");
    await expect(items).toHaveText(["People Ops", ALPHA_NAME, ZETA_NAME]); // sorted; never `hidden`
    await expect(items.nth(0)).toHaveAttribute("aria-checked", "true");
    await expect(items.nth(1)).toHaveAttribute("aria-checked", "false");
    await expect(items.nth(2)).toHaveAttribute("aria-checked", "false");
    await expect(menu).not.toContainText(HIDDEN_NAME);

    await items.nth(1).click();
    await expect(page).toHaveURL(workspaceUrl(alpha, "dashboard"));
    await expect(switcher).toContainText(ALPHA_NAME);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Dashboard");
    await expect(page.getByTestId("area-page")).toHaveAttribute("data-area", "dashboard");
    await expect(userMenu).toContainText("Viewer"); // the role in the current Workspace
    await expect(userMenu).not.toContainText("Builder");
    const sidebar = page.getByTestId("sidebar");
    const dashboardLink = sidebar.getByRole("link", { name: "Dashboard", exact: true });
    await expect(dashboardLink).toHaveAttribute("href", `/w/${alpha}/dashboard`);
    await expect(dashboardLink).toHaveAttribute("aria-current", "page");

    await switcher.click();
    await page.getByRole("menuitemradio", { name: ZETA_NAME }).click();
    await expect(page).toHaveURL(workspaceUrl(zeta, "dashboard"));
    await expect(userMenu).toContainText("Workspace Admin");
    await expect(page.getByRole("menuitemradio")).toHaveCount(0); // the menu closed

    // The Workspace is kept on reload and when another area is opened.
    await page.reload();
    await expect(switcher).toContainText(ZETA_NAME);
    await sidebar.getByRole("link", { name: "Channels" }).click();
    await expect(page).toHaveURL(workspaceUrl(zeta, "channels"));

    await switcher.click();
    await page.getByRole("menuitemradio", { name: "People Ops" }).click();
    await expect(page).toHaveURL(workspaceUrl(peopleOps, "channels"));
    await expect(userMenu).toContainText("Builder");
    expect(seen.requests.filter((request) => IDENTITY_PARAMS.test(request.url))).toEqual([]);
    expect(seen.problems).toEqual([]);
  });
});

test("AC6 TC-6-2: an unreachable Workspace is Page not found with no data of it, and the API says 404 not_found like for a random id", async ({
  browser,
}) => {
  const api = ApiSession.fromCookies(
    state.cookies.filter((cookie) => cookie.name.startsWith("ei_")),
  );
  const random = randomUUID();

  const randomAnswer = await api.workspace(random);
  expectDetail(randomAnswer, 404, "not_found");
  expectSameAnswer(await api.workspace(hidden), randomAnswer, "same Organization, not a member");
  expectSameAnswer(
    await api.workspace(foreign.workspaceId),
    randomAnswer,
    "another Organization's Workspace",
  );
  // Reachable Workspaces answer with the caller's own role in each.
  for (const [id, name, role] of [
    [peopleOps, "People Ops", /builder/i],
    [alpha, ALPHA_NAME, /viewer/i],
    [zeta, ZETA_NAME, /workspace_?\s?admin/i],
  ] as const) {
    const own = await api.workspace(id);
    expect(own.status).toBe(200);
    expect(own.json).toMatchObject({ id, name });
    expect((own.json as { role: string }).role).toMatch(role);
  }

  await withPage(browser, state, async (page) => {
    const targets: { id: string; secrets: string[] }[] = [
      { id: hidden, secrets: [hidden, HIDDEN_NAME] },
      {
        id: foreign.workspaceId,
        secrets: [foreign.workspaceId, foreign.workspaceName, "QA EA-22"],
      },
      { id: random, secrets: [] },
      { id: "not-a-uuid", secrets: [] },
    ];
    for (const target of targets) {
      await page.goto(`/w/${target.id}/dashboard`);
      const notFound = page.getByTestId("not-found");
      await expect(notFound, target.id).toBeVisible();
      await expect(notFound.getByRole("heading", { level: 1 })).toHaveText("Page not found");
      await expect(notFound).toContainText(
        "This page does not exist or you do not have access to it.",
      );
      await expect(page).toHaveTitle("Page not found · ei-ai");
      const html = await page.content();
      const text = await page.locator("body").innerText();
      for (const secret of target.secrets) {
        expect(html, `the page for ${target.id} leaks ${secret}`).not.toContain(secret);
        expect(text).not.toContain(secret);
      }
    }
    // Other not-found paths of the same page.
    for (const unknownPath of [`/w/${peopleOps}/not-an-area`, "/not-a-page", "/w/"]) {
      await page.goto(unknownPath);
      await expect(page.getByTestId("not-found"), unknownPath).toBeVisible();
    }
    // The link goes back to the user's own Dashboard.
    await page.goto(`/w/${hidden}/dashboard`);
    await page.getByRole("link", { name: "Go to your dashboard" }).click();
    await expect(page).toHaveURL(workspaceUrl(peopleOps));
  });
});

// ---------------------------------------------------------------------------------------------
// AC7 matches the design
// ---------------------------------------------------------------------------------------------

test("AC7: the sign-in page has the texts, labels and test ids of the SignIn artboard", async ({
  browser,
}) => {
  await withPage(browser, undefined, async (page) => {
    const seen = watch(page);
    await page.goto("/sign-in");
    await expect(page).toHaveTitle("Sign in · ei-ai");
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await expect(page.getByText("ei-ai", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Sign in");
    await expect(page.getByText("Use and manage your organization's assistants.")).toBeVisible();

    const form = page.getByTestId("sign-in-form");
    const email = form.getByLabel("Work email");
    const password = form.getByLabel("Password", { exact: true });
    await expect(email).toHaveAttribute("type", "email");
    await expect(email).toHaveAttribute("autocomplete", "username");
    await expect(password).toHaveAttribute("type", "password");
    await expect(password).toHaveAttribute("autocomplete", "current-password");
    await expect(page.getByRole("link", { name: "Forgot password?" })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
    await expect(form.getByRole("button", { name: "Sign in" })).toBeVisible();
    await expect(page.getByText("Accounts are created by your organization admin.")).toBeVisible();

    // Deliberate differences from the artboard: no 2FA note, no language picker, no API status.
    await expect(page.getByText(/2FA|two-factor|\bLater\b/i)).toHaveCount(0);
    await expect(page.locator("select")).toHaveCount(0);
    await expect(page.getByText(/API:/)).toHaveCount(0);
    await expect(page.getByLabel(/language/i)).toHaveCount(0);

    // Fonts of the DSN-01 tokens.
    const font = await page.evaluate(() => getComputedStyle(document.body).fontFamily);
    expect(font).toContain("IBM Plex Sans");
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: path.join(SCREENSHOTS, "ac7-sign-in.png") });

    // The error state, for the comparison with the artboard.
    await page.route("**/api/auth/sign-in", (route) =>
      route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ detail: "invalid_credentials" }),
      }),
    );
    await page.getByLabel("Work email").fill("someone@mekongdevworks.example");
    await page.getByLabel("Password", { exact: true }).fill("Some-secret-1234");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByTestId("sign-in-error")).toHaveText(MSG.invalid);
    await page.screenshot({ path: path.join(SCREENSHOTS, "ac7-sign-in-error.png") });

    expect(seen.requests.filter((request) => IDENTITY_PARAMS.test(request.url))).toEqual([]);
    expect(withoutExpected401(seen.problems)).toEqual([]);
  });
});

test("AC7 TC-7-2: the Sidebar has the logo, switchers, groups and links of the Sidebar artboard in order", async ({
  browser,
}) => {
  await withPage(browser, state, async (page) => {
    const seen = watch(page);
    await page.goto(`/w/${peopleOps}/dashboard`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Dashboard");

    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav).toBeVisible();
    const sidebar = page.getByTestId("sidebar");
    await expect(sidebar).toBeVisible();
    const box = await sidebar.boundingBox();
    expect(Math.round(box?.width ?? 0), "Sidebar width").toBe(248);

    await expect(sidebar.getByText("ei-ai", { exact: true })).toBeVisible();
    await expect(sidebar.getByText("Prototype", { exact: true })).toBeVisible();
    const orgSwitcher = page.getByTestId("org-switcher");
    await expect(orgSwitcher).toContainText("Organization");
    await expect(orgSwitcher).toContainText("Mekong Devworks");
    const workspaceSwitcher = page.getByTestId("workspace-switcher");
    await expect(workspaceSwitcher).toContainText("Workspace");
    await expect(workspaceSwitcher).toContainText("People Ops");
    await expect(sidebar.getByText("Chat", { exact: true })).toHaveCount(0);

    // Order from the top: switchers, then every group heading followed by its links, then the user.
    const centres: { label: string; y: number }[] = [];
    const yOf = async (label: string, locator: Locator) => {
      await expect(locator, label).toHaveCount(1);
      const rect = await locator.boundingBox();
      expect(rect, label).not.toBeNull();
      centres.push({ label, y: (rect?.y ?? 0) + (rect?.height ?? 0) / 2 });
    };
    await yOf("org-switcher", orgSwitcher);
    await yOf("workspace-switcher", workspaceSwitcher);
    // A Builder sees 8 of the 11 areas: no Review group, no Organization.
    await expect(sidebar.getByText("Review", { exact: true })).toHaveCount(0);
    for (const hidden of ["Conversations", "Unanswered", "Organization"]) {
      await expect(sidebar.getByRole("link", { name: hidden, exact: true }), hidden).toHaveCount(0);
    }
    for (const { group, items } of BUILDER_NAV) {
      await yOf(`group ${group}`, sidebar.getByText(group, { exact: true }));
      for (const [label, slug] of items) {
        const link = sidebar.getByRole("link", { name: label, exact: true });
        await yOf(`link ${label}`, link);
        await expect(link).toHaveAttribute("href", `/w/${peopleOps}/${slug}`);
      }
    }
    await yOf("user-menu", page.getByTestId("user-menu"));
    const ys = centres.map((entry) => entry.y);
    expect(ys, centres.map((entry) => entry.label).join(" < ")).toEqual(
      [...ys].sort((a, b) => a - b),
    );
    expect(new Set(ys).size).toBe(ys.length);

    // Exactly the current link is marked.
    await expect(sidebar.locator('[aria-current="page"]')).toHaveCount(1);
    await expect(sidebar.getByRole("link", { name: "Dashboard", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );

    // The user block: initials, display name and the role in the current Workspace.
    const userMenu = page.getByTestId("user-menu");
    await expect(userMenu).toContainText(main.name);
    await expect(userMenu).toContainText("Builder");
    await page.screenshot({ path: path.join(SCREENSHOTS, "ac7-shell.png") });

    await userMenu.click();
    await expect(page.getByText("Sign out", { exact: true })).toBeVisible();
    await page.screenshot({ path: path.join(SCREENSHOTS, "ac7-shell-user-menu.png") });
    await page.reload();

    await page.getByTestId("workspace-switcher").click();
    await page.screenshot({ path: path.join(SCREENSHOTS, "ac7-shell-workspace-menu.png") });
    await page.reload();

    // The Organization switcher: one item, the user's Organization, marked as current.
    await page.getByTestId("org-switcher").click();
    const orgItems = page.getByRole("menu").locator('[role^="menuitem"]');
    await expect(orgItems).toHaveCount(1);
    await expect(orgItems).toContainText("Mekong Devworks");
    const marked = await orgItems.evaluate(
      (element) =>
        element.getAttribute("aria-checked") === "true" ||
        (element.getAttribute("aria-current") !== null &&
          element.getAttribute("aria-current") !== "false"),
    );
    expect(marked, "the Organization item is marked as current").toBe(true);
    await page.screenshot({ path: path.join(SCREENSHOTS, "ac7-shell-org-menu.png") });

    expect(seen.requests.filter((request) => IDENTITY_PARAMS.test(request.url))).toEqual([]);
    expect(seen.problems).toEqual([]);
  });
});

test("AC7 TC-7-3: every area is an empty page with the label as heading, title and data-area", async ({
  browser,
}) => {
  await withPage(browser, state, async (page) => {
    const seen = watch(page);
    await page.goto(`/w/${peopleOps}/dashboard`);
    const sidebar = page.getByTestId("sidebar");
    for (const { items } of BUILDER_NAV) {
      for (const [label, slug] of items) {
        await sidebar.getByRole("link", { name: label, exact: true }).click();
        await expect(page, label).toHaveURL(workspaceUrl(peopleOps, slug));
        await expect(page.getByRole("heading", { level: 1 }), label).toHaveText(label);
        if (slug === "members") {
          // EA-23: Members & roles is a real page now.
          await expect(page.getByTestId("members-page"), label).toBeVisible();
        } else if (slug === "knowledge") {
          // EA-32: Knowledge is a real page now.
          await expect(page.getByTestId("knowledge-page"), label).toBeVisible();
        } else {
          const area = page.getByTestId("area-page");
          await expect(area, label).toHaveAttribute("data-area", slug);
          await expect(area, label).toContainText("Nothing here yet.");
        }
        await expect(page, label).toHaveTitle(`${label} · ei-ai`);
        await expect(sidebar.locator('[aria-current="page"]'), label).toHaveCount(1);
        await expect(sidebar.getByRole("link", { name: label, exact: true })).toHaveAttribute(
          "aria-current",
          "page",
        );
      }
    }
    // The areas a Builder cannot use are "No access" inside the shell (EA-23).
    for (const slug of BUILDER_HIDDEN) {
      await page.goto(`/w/${peopleOps}/${slug}`);
      const forbidden = page.getByTestId("area-forbidden");
      await expect(forbidden, slug).toBeVisible();
      await expect(forbidden.getByRole("heading", { level: 1 })).toHaveText("No access");
      await expect(sidebar, slug).toBeVisible();
    }
    // Opening an area by URL gives the same page.
    await page.goto(`/w/${peopleOps}/skills`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Skills & Connectors");
    expect(seen.problems).toEqual([]);
  });
});

// ---------------------------------------------------------------------------------------------
// NFR1 accessibility basics and touch targets
// ---------------------------------------------------------------------------------------------

test("NFR1: the auth pages have labelled inputs, keyboard focus order with visible focus, 44 px controls", async ({
  browser,
}) => {
  const invited = inviteUser({ label: "nfr", role: "builder", workspaceId: peopleOps });
  const pages = [
    { name: "sign-in", url: "/sign-in" },
    { name: "forgot-password", url: "/forgot-password" },
    { name: "set-password", url: `${ADMIN}/set-password#token=${invited.link.token}` },
    { name: "reset", url: `${ADMIN}/reset#token=${invited.link.token}` },
  ];
  await withPage(browser, undefined, async (page) => {
    for (const target of pages) {
      await page.goto(target.url);
      await expect(page.getByRole("heading", { level: 1 }), target.name).toBeVisible();
      await expect(page.locator("html")).toHaveAttribute("lang", "en");

      const inputs = page.locator("input:visible");
      const inputCount = await inputs.count();
      expect(inputCount, `${target.name}: inputs`).toBeGreaterThan(0);
      for (let index = 0; index < inputCount; index++) {
        const input = inputs.nth(index);
        expect(
          await heightOf(input),
          `${target.name}: input ${index} height`,
        ).toBeGreaterThanOrEqual(44);
        const label = await input.evaluate((element) => {
          const bound = (element as HTMLInputElement).labels?.[0];
          if (!bound) return "";
          const visible = getComputedStyle(bound).display !== "none";
          return visible ? (bound.textContent ?? "").trim() : "";
        });
        expect(label, `${target.name}: input ${index} has a visible bound label`).not.toBe("");
      }
      const buttons = page.locator("button:visible");
      const buttonCount = await buttons.count();
      expect(buttonCount, `${target.name}: buttons`).toBeGreaterThan(0);
      for (let index = 0; index < buttonCount; index++) {
        expect(
          await heightOf(buttons.nth(index)),
          `${target.name}: button ${index} height`,
        ).toBeGreaterThanOrEqual(44);
      }

      // Tab reaches every visible input and button, and the focused element shows a focus indicator.
      await page.evaluate(() => {
        document
          .querySelectorAll("input, button, a[href]")
          .forEach((element, index) => element.setAttribute("data-qa-order", String(index)));
        (document.activeElement as HTMLElement | null)?.blur();
      });
      const wanted = await page
        .locator("input:visible, button:visible")
        .evaluateAll((elements) =>
          elements.map((element) => element.getAttribute("data-qa-order")),
        );
      const reached = new Set<string>();
      for (let press = 0; press < 12; press++) {
        await page.keyboard.press("Tab");
        const focus = await page.evaluate(() => {
          const element = document.activeElement as HTMLElement | null;
          if (!element || element === document.body) return null;
          const style = getComputedStyle(element);
          return {
            order: element.getAttribute("data-qa-order"),
            tag: element.tagName,
            outline: style.outlineStyle !== "none" && Number.parseFloat(style.outlineWidth) > 0,
            shadow: style.boxShadow !== "none",
          };
        });
        if (!focus) break;
        if (focus.order) reached.add(focus.order);
        expect(
          focus.outline || focus.shadow,
          `${target.name}: <${focus.tag}> #${focus.order} shows no focus indicator (outline or box-shadow)`,
        ).toBe(true);
      }
      for (const order of wanted) {
        expect(
          reached.has(order ?? ""),
          `${target.name}: element #${order} is not reachable by Tab`,
        ).toBe(true);
      }
    }
  });
});

test("NFR1 TC-NFR1-2: sign-in text and controls reach WCAG AA contrast and the form works from the keyboard", async ({
  browser,
}) => {
  await withPage(browser, undefined, async (page) => {
    let posts = 0;
    await page.route("**/api/auth/sign-in", async (route) => {
      posts += 1;
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ detail: "invalid_credentials" }),
      });
    });
    await page.goto("/sign-in");
    const checks: [string, Locator][] = [
      ["heading", page.getByRole("heading", { level: 1 })],
      ["intro text", page.getByText("Use and manage your organization's assistants.")],
      ["email label", page.getByText("Work email", { exact: true })],
      ["password label", page.getByText("Password", { exact: true })],
      ["email input", page.getByLabel("Work email")],
      ["forgot link", page.getByRole("link", { name: "Forgot password?" })],
      ["sign-in button", page.getByRole("button", { name: "Sign in" })],
      ["footer text", page.getByText("Accounts are created by your organization admin.")],
    ];
    for (const [name, locator] of checks) {
      const ratio = await contrastRatio(locator.first());
      expect(ratio, `${name} contrast ${ratio.toFixed(2)}`).toBeGreaterThanOrEqual(4.5);
    }

    // Keyboard only: type the email, Tab to the password (the Forgot password link may sit in between),
    // type the password, Enter.
    await page.getByLabel("Work email").focus();
    await page.keyboard.type("someone@mekongdevworks.example");
    for (let press = 0; press < 3; press++) {
      await page.keyboard.press("Tab");
      const onPassword = await page.evaluate(
        () => (document.activeElement as HTMLInputElement | null)?.type === "password",
      );
      if (onPassword) break;
    }
    await page.keyboard.type("Some-secret-1234");
    await page.keyboard.press("Enter");
    const alert = page.getByTestId("sign-in-error");
    await expect(alert).toHaveText(MSG.invalid);
    expect(posts).toBe(1);
    const alertRatio = await contrastRatio(alert);
    expect(alertRatio, `error alert contrast ${alertRatio.toFixed(2)}`).toBeGreaterThanOrEqual(4.5);

    // Field errors are tied to their input or announced.
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await page.goto("/sign-in");
    await page.getByRole("button", { name: "Sign in" }).click();
    for (const [text, label] of [
      ["Enter your email", "Work email"],
      ["Enter your password", "Password"],
    ] as const) {
      const message = page.getByText(text);
      await expect(message).toBeVisible();
      const input = page.getByLabel(label, { exact: true });
      const announced = await message.evaluate(
        (element, inputId) => {
          const inAlert = element.closest('[role="alert"]') !== null;
          const input = inputId ? document.getElementById(inputId) : null;
          const describedBy = input?.getAttribute("aria-describedby") ?? "";
          const linked = describedBy
            .split(/\s+/)
            .some((id) => id !== "" && document.getElementById(id)?.contains(element));
          return inAlert || linked;
        },
        await input.getAttribute("id"),
      );
      expect(announced, `"${text}" is announced (role=alert or aria-describedby)`).toBe(true);
    }
  });
});
