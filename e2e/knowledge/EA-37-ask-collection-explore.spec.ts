// EA-37 (KB-06): the exploratory flows of "Ask this collection", automated as a Playwright script because the
// Chrome DevTools MCP tools were not available in the QA session (the run-mode fallback). Black-box, from
// .work/EA-37/contract.md only. Tier @slow (real chat model + embedding model):
//   EA37_EXPLORE=1 npm run e2e:full -- e2e/knowledge/EA-37-ask-collection-explore.spec.ts
// What it does, one test per flow (the numbers match docs/qa/knowledge/EA-37-ask-collection.md):
//   X1 happy path as a person (screenshots)            X2 artboard vs live panel (computed styles, screenshots)
//   X3 console / network / stream of the main page      X4 performance (LCP, long tasks, event timing)
//   X5 input methods (IME, paste, double click, held Enter)   X6 state changes during an answer
//   X7 roles without Knowledge rights and an expired session   X8 responsive widths and long content
//   X9 the chat model dies in the middle of an answer
// Findings are written to .work/EA-37/explore-results.json and screenshots to .work/EA-37/screenshots/.
// Data: `qa-EA37-<run> Handbook` and `... Managers`, removed in afterAll (row counts proven equal).
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { DESKTOP, ROOT, contrastRatio, watch, type ApiSession } from "../support/ea22";
import { withSession } from "../support/ea23";
import { apiOf } from "../support/ea33";
import {
  ANSWERED_EN,
  CHAT_SERVICE,
  LEAVE_PASSAGES,
  Q,
  SCREENSHOTS_37,
  WORK_37,
  answerText,
  ask,
  buildAskFixtures,
  cleanup37,
  clickAsk,
  counts37,
  markerRows37,
  mockSse,
  observeAnswer,
  openAskPanel,
  passageRows,
  readAnswerLog,
  saveResult,
  routeToFake,
  settle,
  startFakeAsk,
  startService,
  stopService,
  waitAskWorks,
  withoutAskAbort,
  type AskFixtures,
  type Counts37,
} from "../support/ea37";

// Exploration, not a regression test: skipped in the regular suite unless EA37_EXPLORE=1.
test.skip(!process.env.EA37_EXPLORE, "set EA37_EXPLORE=1 to run the EA-37 exploratory flows");

test.describe.configure({ mode: "default", timeout: 900_000 });

let baseline: Counts37 | undefined;
let fx: Required<Pick<AskFixtures, "ws" | "thao" | "linh" | "handbook" | "managers">>;
let son: ApiSession;
let ha: ApiSession;
// Every finding is merged into the JSON file at once: a failed test restarts the worker, which would lose memory.
const RESULTS_FILE = "explore-results.json";
const results: Record<string, unknown> = new Proxy(
  {},
  {
    set(_target, key, value) {
      const file = path.join(WORK_37, RESULTS_FILE);
      let current: Record<string, unknown> = {};
      try {
        current = JSON.parse(fs.readFileSync(file, "utf8")) as Record<string, unknown>;
      } catch {
        // first finding
      }
      current[String(key)] = value;
      saveResult(RESULTS_FILE, current);
      return true;
    },
  },
);

test.beforeAll(async () => {
  test.setTimeout(1_800_000);
  await cleanup37();
  baseline = counts37();
  fx = (await buildAskFixtures(["handbook", "managers"])) as typeof fx;
  son = await apiOf("son");
  ha = await apiOf("ha");
  fs.mkdirSync(SCREENSHOTS_37, { recursive: true });
});

test.afterAll(async () => {
  test.setTimeout(900_000);
  try {
    startService(CHAT_SERVICE);
  } catch {
    // reported by the test that stopped it
  }
  await cleanup37();
  if (baseline) expect(counts37(), "rows left behind").toEqual(baseline);
  expect(markerRows37(), "rows with the EA-37 marker left behind").toEqual([]);
});

const shot = (page: Page, name: string) =>
  page.getByTestId("ask-panel").screenshot({ path: path.join(SCREENSHOTS_37, name) });

// ---------------------------------------------------------------------------------------------
// X1 Happy path as a person
// ---------------------------------------------------------------------------------------------

test("X1: happy path with the real model (both marry questions), keyboard reachable, screenshots", async ({
  browser,
}) => {
  await withSession(browser, fx.thao, async (page) => {
    const seen = watch(page);
    await openAskPanel(page, fx.ws, fx.handbook.id);
    await page.getByTestId("ask-panel").scrollIntoViewIfNeeded();
    await page.screenshot({
      path: path.join(SCREENSHOTS_37, "x1-page-before.png"),
      fullPage: true,
    });
    for (const [question, name] of [
      [Q.marryVi, "x1-marry-vi.png"],
      [Q.marryEn, "x1-marry-en.png"],
    ] as const) {
      await page.getByTestId("ask-question").fill(question);
      await page.getByTestId("ask-question").press("Enter");
      expect(await settle(page)).toBe("answered");
      await shot(page, name);
      results[`x1 ${question}`] = {
        answer: await answerText(page),
        rows: await passageRows(page),
      };
    }
    // Keyboard only: Tab from the input reaches the button; the focus ring is visible.
    await page.getByTestId("ask-question").focus();
    await page.keyboard.press("Tab");
    await expect(page.getByTestId("ask-submit")).toBeFocused();
    const outline = await page
      .getByTestId("ask-submit")
      .evaluate(
        (el) => `${getComputedStyle(el).outlineStyle} ${getComputedStyle(el).outlineWidth}`,
      );
    results["x1 focus outline of Ask"] = outline;
    await page.screenshot({ path: path.join(SCREENSHOTS_37, "x1-page-after.png"), fullPage: true });
    results["x1 console/network problems"] = seen.problems;
    expect(withoutAskAbort(seen.problems)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------------------------
// X2 Artboard vs live panel
// ---------------------------------------------------------------------------------------------

test("X2: the live panel against the CollectionDetail artboard (computed styles of every element, screenshots)", async ({
  browser,
}) => {
  const file = `file:///${ROOT.replace(/\\/g, "/")}/docs/design/canvas/CollectionDetail.dc.html`;
  const measure = (kind: string): Record<string, Record<string, string>> => {
    const root: ParentNode = document;
    const out: Record<string, Record<string, string>> = {};
    const take = (key: string, el: Element | null | undefined): void => {
      if (!el) {
        out[key] = { missing: "true" };
        return;
      }
      const s = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      out[key] = {
        font: `${s.fontSize} / ${s.lineHeight} / ${s.fontWeight}`,
        color: s.color,
        bg: s.backgroundColor,
        border: `${s.borderTopWidth} ${s.borderTopColor}`,
        radius: s.borderTopLeftRadius,
        padding: s.padding,
        margin: `${s.marginTop} ${s.marginBottom}`,
        gap: s.gap,
        height: `${Math.round(r.height)}`,
        family: (s.fontFamily.split(",")[0] ?? "").replace(/"/g, ""),
      };
    };
    const byText = (selector: string, text: string): Element | undefined =>
      [...root.querySelectorAll(selector)].find((el) =>
        (el.textContent ?? "").trim().startsWith(text),
      );
    if (kind === "artboard") {
      const section = [...root.querySelectorAll("section")].find((s) =>
        (s.textContent ?? "").includes("Ask this collection"),
      );
      take("panel", section);
      take("heading", section?.querySelector("h2"));
      take("helper", section?.querySelector("p"));
      take("input", section?.querySelector("input"));
      take("button", section?.querySelector("button"));
      take("answer box", byText("div", "Nhân viên được nghỉ") ?? null);
      take("citation in answer", section?.querySelector("span[style*='0B6B5C']"));
      take("passages title", byText("div", "Passages found"));
      const rowsList = [...(section?.querySelectorAll("div[style*='font-size: 13px']") ?? [])];
      take("cited row", rowsList[0]);
      take("cited number", rowsList[0]?.children[0]);
      take("source", rowsList[0]?.children[1]);
      take("score", rowsList[0]?.children[2]);
      take("uncited row", rowsList[1]);
    } else {
      const q = (id: string): Element | null => root.querySelector(`[data-testid="${id}"]`);
      take("panel", q("ask-panel"));
      take("heading", q("ask-panel")?.querySelector("h2"));
      take("helper", q("ask-panel")?.querySelector("p"));
      take("input", q("ask-question"));
      take("button", q("ask-submit"));
      take("answer box", q("ask-answer"));
      take("citation in answer", q("ask-citation"));
      take("passages title", q("ask-passages")?.firstElementChild);
      const live = [...root.querySelectorAll('[data-testid="ask-passage"]')];
      take("cited row", live[0]);
      take("cited number", live[0]?.firstElementChild);
      take("source", live[0]?.querySelector('[data-testid="ask-passage-source"]'));
      take("score", live[0]?.querySelector('[data-testid="ask-passage-score"]'));
      take("uncited row", live[1]);
    }
    return out;
  };

  const context = await browser.newContext({ viewport: { width: 1440, height: 1260 } });
  const art = await context.newPage();
  await art.goto(file);
  await art.waitForTimeout(1500);
  const artboard = await art.evaluate(measure, "artboard");
  await art.screenshot({ path: path.join(SCREENSHOTS_37, "x2-artboard.png"), fullPage: true });
  const artSection = art.locator("section", { hasText: "Ask this collection" }).last();
  await artSection
    .screenshot({ path: path.join(SCREENSHOTS_37, "x2-artboard-panel.png") })
    .catch(() => undefined);
  await context.close();

  await withSession(browser, fx.thao, async (page) => {
    await page.setViewportSize({ width: 1440, height: 1260 });
    // The same content as the artboard: three passages 0.91 / 0.58 / 0.47, the first cited.
    await mockSse(page, [
      [
        "passages",
        {
          language: "vi",
          passages: [
            {
              number: 1,
              title: "Leave Policy 2026",
              section: "§4.1 Personal leave",
              page: null,
              score: 0.91,
            },
            {
              number: 2,
              title: "Leave Policy 2026",
              section: "§4.3 Bereavement leave",
              page: null,
              score: 0.58,
            },
            {
              number: 3,
              title: "Benefits Summary 2026",
              section: "Wedding gift row",
              page: null,
              score: 0.47,
            },
          ],
        },
      ],
      [
        "done",
        {
          outcome: "answered",
          answer:
            "Nhân viên được nghỉ 3 ngày hưởng nguyên lương khi kết hôn; con kết hôn được nghỉ 1 ngày [1].",
          citations: [1],
        },
      ],
    ]);
    await openAskPanel(page, fx.ws, fx.handbook.id);
    await clickAsk(page, "Kết hôn được nghỉ mấy ngày?");
    expect(await settle(page, 20_000)).toBe("answered");
    const live = await page.evaluate(measure, "live");
    await shot(page, "x2-live-panel.png");
    await page.screenshot({ path: path.join(SCREENSHOTS_37, "x2-live-page.png"), fullPage: true });
    const diffs: string[] = [];
    for (const key of Object.keys(artboard)) {
      for (const prop of Object.keys(artboard[key] ?? {})) {
        const a = artboard[key]?.[prop];
        const l = live[key]?.[prop];
        if (a !== l) diffs.push(`${key}.${prop}: artboard ${a} | live ${l}`);
      }
    }
    results["x2 style differences (artboard | live)"] = diffs;
    results["x2 artboard"] = artboard;
    results["x2 live"] = live;
    test.info().annotations.push({ type: "observation", description: diffs.join("\n") });
  });
});

// ---------------------------------------------------------------------------------------------
// X3 / X4 Console, network, stream and performance on the main page
// ---------------------------------------------------------------------------------------------

test("X3+X4: console, requests (status, time, headers, body), the stream is not buffered, LCP / long tasks / event timing", async ({
  browser,
}) => {
  await withSession(browser, fx.thao, async (page) => {
    const seen = watch(page);
    const calls: Record<string, unknown>[] = [];
    page.on("requestfinished", async (request) => {
      const url = new URL(request.url());
      const response = await request.response();
      const timing = request.timing();
      calls.push({
        method: request.method(),
        path: url.pathname,
        origin: url.origin,
        status: response?.status(),
        ms: Math.round(timing.responseEnd),
      });
    });
    await page.addInitScript(() => {
      const w = window as unknown as { __perf: Record<string, unknown[]> };
      w.__perf = { lcp: [], longtask: [], event: [] };
      const watchType = (type: string, key: string, extra?: PerformanceObserverInit): void => {
        try {
          new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
              (w.__perf[key] as unknown[]).push({
                name: entry.name,
                start: Math.round(entry.startTime),
                duration: Math.round(entry.duration),
              });
            }
          }).observe({ type, buffered: true, ...extra } as PerformanceObserverInit);
        } catch {
          // type not supported
        }
      };
      watchType("largest-contentful-paint", "lcp");
      watchType("longtask", "longtask");
      watchType("event", "event", { durationThreshold: 16 } as PerformanceObserverInit);
    });
    await observeAnswer(page);
    const asks: {
      url: string;
      headers: Record<string, string>;
      body: string | null;
      status: number;
      respHeaders: Record<string, string>;
    }[] = [];
    page.on("response", (response) => {
      if (
        response.request().method() === "POST" &&
        /\/ask$/.test(new URL(response.url()).pathname)
      ) {
        asks.push({
          url: response.url(),
          headers: response.request().headers(),
          body: response.request().postData(),
          status: response.status(),
          respHeaders: response.headers(),
        });
      }
    });
    await openAskPanel(page, fx.ws, fx.handbook.id);
    await clickAsk(page, Q.marryEn);
    expect(await settle(page)).toBe("answered");
    const { clickAt, samples } = await readAnswerLog(page);
    const answering = samples.filter((s) => s.outcome === "answering" && s.text !== "");
    const done = samples.find((s) => s.outcome === "answered");
    const perf = await page.evaluate(() => (window as unknown as { __perf: unknown }).__perf);
    results["x3 console/network problems"] = seen.problems;
    results["x3 requests"] = calls.filter((c) => String(c.path).startsWith("/api"));
    results["x3 ask request"] = asks.map((a) => ({
      url: a.url,
      sentHeaders: Object.keys(a.headers).sort(),
      body: a.body,
      status: a.status,
      respHeaders: {
        "content-type": a.respHeaders["content-type"],
        "cache-control": a.respHeaders["cache-control"],
        "x-accel-buffering": a.respHeaders["x-accel-buffering"] ?? "(not passed on by the proxy)",
      },
    }));
    results["x3 stream timing in the page (ms after the click)"] = {
      firstText: Math.round((answering[0]?.t ?? 0) - clickAt),
      done: Math.round((done?.t ?? 0) - clickAt),
      growthSteps: new Set(answering.map((s) => s.text)).size,
    };
    results["x4 performance (page)"] = perf;
    const body = JSON.parse(asks[0]?.body ?? "{}") as Record<string, unknown>;
    expect(Object.keys(body).sort()).toEqual(["principal", "question"]);
    const identityHits = JSON.stringify(calls).match(/org_id|user_id|workspace_id/g);
    expect(identityHits, "no identity params from the client").toBeNull();
    const origins = new Set(calls.map((c) => String(c.origin)));
    results["x3 origins"] = [...origins];
    expect(origins.size, "all requests go to the admin origin").toBe(1);
    expect(withoutAskAbort(seen.problems)).toEqual([]);
    const slow = calls.filter((c) => Number(c.ms) > 1000 && !String(c.path).endsWith("/ask"));
    results["x3 slow requests (> 1 s, other than ask)"] = slow;
    expect(slow).toEqual([]);
    // INP of the interaction: input events during the ask
    const events = (perf as { event: { duration: number; name: string }[] }).event;
    results["x4 worst event duration (ms)"] = Math.max(0, ...events.map((e) => e.duration));
    const long = (perf as { longtask: { duration: number }[] }).longtask;
    results["x4 long tasks"] = long;
  });
});

// ---------------------------------------------------------------------------------------------
// X5 Input methods
// ---------------------------------------------------------------------------------------------

test("X5: Enter during IME composition, 3000-character paste, double click, held Enter", async ({
  browser,
}) => {
  await withSession(browser, fx.thao, async (page) => {
    const recorded = await mockSse(page, ANSWERED_EN);
    await openAskPanel(page, fx.ws, fx.handbook.id);
    const question = page.getByTestId("ask-question");

    // Vietnamese Telex composition: Enter that confirms the composition must not submit.
    await question.focus();
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Input.imeSetComposition", {
      text: "kết hô",
      selectionStart: 6,
      selectionEnd: 6,
    });
    await cdp.send("Input.dispatchKeyEvent", {
      type: "keyDown",
      key: "Enter",
      code: "Enter",
      windowsVirtualKeyCode: 229,
    });
    await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter" });
    await page.waitForTimeout(500);
    results["x5 requests sent by Enter during composition"] = recorded.length;
    await cdp.send("Input.insertText", { text: "kết hôn" });
    await question.fill("");

    // Paste 3000 characters: the limit is 2000.
    await question.focus();
    await page.keyboard.insertText("x".repeat(3000));
    const length = await question.evaluate((el) => (el as HTMLInputElement).value.length);
    results["x5 length after a 3000-character paste"] = length;
    expect(length).toBeLessThanOrEqual(2000);
    await question.fill(Q.marryEn);

    // Double click and held Enter against a stream that lasts 2.5 s (a real answer takes seconds): one request.
    await page.unroute("**/api/workspaces/*/collections/*/ask");
    const fake = await startFakeAsk();
    try {
      await routeToFake(page, fake);
      const script = [
        { event: "passages", data: { language: "en", passages: LEAVE_PASSAGES } },
        { afterMs: 1200, event: "delta", data: { text: "Employees get " } },
        {
          afterMs: 1300,
          event: "done",
          data: { outcome: "answered", answer: "Employees get 3 days [1].", citations: [1] },
        },
      ];
      fake.script(script);
      await question.fill(Q.marryEn);
      await page.getByTestId("ask-submit").dblclick();
      await page.waitForTimeout(1000);
      results["x5 requests sent by a double click on Ask"] = fake.bodies.length;
      expect(fake.bodies.length).toBe(1);
      await settle(page, 15_000);

      fake.script(script);
      await question.fill(Q.marryVi);
      const before = fake.bodies.length;
      await question.focus();
      await page.keyboard.down("Enter");
      for (let i = 0; i < 8; i += 1) {
        await page.waitForTimeout(100);
        await page.keyboard.down("Enter");
      }
      await page.keyboard.up("Enter");
      await page.waitForTimeout(500);
      results["x5 requests sent by a held Enter (answer takes 2.5 s)"] =
        fake.bodies.length - before;
      expect(fake.bodies.length - before).toBe(1);
      await settle(page, 15_000);
    } finally {
      await fake.close();
    }
  });
});

// ---------------------------------------------------------------------------------------------
// X6 State changes during an answer
// ---------------------------------------------------------------------------------------------

test("X6: changing Ask as / Groups while answering, leaving and coming back, refresh, two tabs", async ({
  browser,
}) => {
  test.setTimeout(240_000); // a stuck answer must fail in minutes, not after the 15-minute suite timeout
  await withSession(browser, fx.thao, async (page, context) => {
    await openAskPanel(page, fx.ws, fx.managers.id);
    await page.getByTestId("ask-question").fill(Q.salaryEn);
    await page.getByTestId("ask-submit").click();
    await expect(page.getByTestId("ask-answer"))
      .toHaveAttribute("data-outcome", "answering")
      .catch(() => undefined);
    // Change the controls while the answer runs.
    await page.getByTestId("ask-principal").selectOption("anonymous");
    const stateAfterChange = {
      outcome: await page
        .getByTestId("ask-answer")
        .getAttribute("data-outcome")
        .catch(() => null),
      groupsVisible: await page.getByTestId("ask-groups").isVisible(),
    };
    results["x6 after changing Ask as while answering"] = stateAfterChange;
    const final = await settle(page);
    results["x6 outcome after the change"] = {
      final,
      text: await answerText(page).catch(() => ""),
      rows: await passageRows(page).catch(() => []),
    };
    await page.getByTestId("ask-principal").selectOption("authenticated");

    // Leave to another collection and come back: the panel starts empty.
    await page.goto(`/w/${fx.ws}/knowledge/${fx.handbook.id}`);
    await expect(page.getByTestId("ask-panel")).toBeVisible();
    await expect(page.getByTestId("ask-answer")).toHaveCount(0);
    await expect(page.getByTestId("ask-question")).toHaveValue("");

    // A second tab asking at the same time.
    const second = await context.newPage();
    await openAskPanel(second, fx.ws, fx.handbook.id);
    await Promise.all([clickAsk(page, Q.marryEn), clickAsk(second, Q.marryVi)]);
    const [a, b] = await Promise.all([settle(page), settle(second)]);
    results["x6 two tabs"] = {
      a,
      b,
      aText: await answerText(page),
      bText: await answerText(second),
    };

    // Refresh: panel is empty again.
    await page.reload();
    await expect(page.getByTestId("ask-answer")).toHaveCount(0);
  });
});

// ---------------------------------------------------------------------------------------------
// X7 Roles without Knowledge rights, expired session
// ---------------------------------------------------------------------------------------------

test("X7: a Viewer and a Reviewer never see the panel; an expired session leads to sign-in", async ({
  browser,
}) => {
  for (const [label, session] of [
    ["viewer", son],
    ["reviewer", ha],
  ] as const) {
    await withSession(browser, session, async (page) => {
      await page.goto(`/w/${fx.ws}/knowledge/${fx.handbook.id}`);
      await page.waitForLoadState("networkidle");
      const panel = await page.getByTestId("ask-panel").count();
      results[`x7 ${label} panel count`] = panel;
      results[`x7 ${label} page text`] = (await page.locator("main").innerText()).slice(0, 200);
      await page.screenshot({ path: path.join(SCREENSHOTS_37, `x7-${label}.png`) });
      expect(panel, `${label} never sees the panel`).toBe(0);
    });
    const r = await ask(session, fx.ws, fx.handbook.id, {
      question: Q.marryEn,
      principal: { kind: "authenticated", groups: [] },
    });
    expect(r.status).toBe(403);
  }
});

// ---------------------------------------------------------------------------------------------
// X8 Responsive widths and long content
// ---------------------------------------------------------------------------------------------

test("X8: 1440 / 1024 / 768 / 375 px and a 200 % zoom: no horizontal overflow, 44 px targets; realistic long content and an extreme unbroken string", async ({
  browser,
}) => {
  const variants: Record<string, { title: string; section: string; answer: string }> = {
    // A long file name without spaces, a long Vietnamese section and a long answer made of normal words.
    realistic: {
      title: "Quy_che_nghi_phep_nam_2026_ban_chinh_sua_cuoi_cung_v3_final_final",
      section:
        "§4.1 Điều kiện nghỉ phép năm, nghỉ không lương và nghỉ việc riêng theo quy định của công ty",
      answer:
        "Nhân viên được nghỉ 3 ngày hưởng nguyên lương khi kết hôn; con kết hôn được nghỉ 1 ngày. ".repeat(
          6,
        ) + "[1]",
    },
    // 288 characters without a single space, in the title and in the answer.
    extreme: {
      title: "Averyveryveryverylongunbrokenwordwithoutanyspaces".repeat(6),
      section: "Averyveryveryverylongunbrokenwordwithoutanyspaces".repeat(3),
      answer: `${"Averyveryveryverylongunbrokenwordwithoutanyspaces".repeat(6)} [1]`,
    },
  };
  await withSession(browser, fx.thao, async (page) => {
    for (const [variant, content] of Object.entries(variants)) {
      await page.unroute("**/api/workspaces/*/collections/*/ask").catch(() => undefined);
      await mockSse(page, [
        [
          "passages",
          {
            language: "vi",
            passages: [
              { number: 1, title: content.title, section: content.section, page: 12, score: 0.912 },
              ...LEAVE_PASSAGES.slice(1),
            ],
          },
        ],
        ["delta", { text: content.answer }],
        ["done", { outcome: "answered", answer: content.answer, citations: [1] }],
      ]);
      for (const [width, height] of [
        [1440, 900],
        [1024, 768],
        [768, 1024],
        [375, 800],
        [720, 450],
      ] as const) {
        await page.setViewportSize({ width, height });
        await openAskPanel(page, fx.ws, fx.managers.id);
        await clickAsk(page, "long content?");
        expect(await settle(page, 20_000)).toBe("answered");
        const overflow = await page.evaluate(() => ({
          doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          panel: (() => {
            const el = document.querySelector('[data-testid="ask-panel"]') as HTMLElement;
            return el.scrollWidth - el.clientWidth;
          })(),
        }));
        const targets = await page.evaluate(() =>
          ["ask-principal", "ask-groups", "ask-question", "ask-submit"].map((id) => {
            const r = (
              document.querySelector(`[data-testid="${id}"]`) as HTMLElement
            ).getBoundingClientRect();
            return { id, w: Math.round(r.width), h: Math.round(r.height) };
          }),
        );
        results[`x8 ${variant} ${width}px`] = { overflow, targets };
        await page.getByTestId("ask-panel").scrollIntoViewIfNeeded();
        await page.screenshot({
          path: path.join(SCREENSHOTS_37, `x8-${variant}-${width}.png`),
          fullPage: false,
        });
        // 375 px: the page overflow is the known Q2-1 (pre-existing console layout), recorded in results, not asserted.
        if (variant === "realistic" && width > 375) {
          expect
            .soft(overflow.doc, `${width}px: no horizontal scroll of the page`)
            .toBeLessThanOrEqual(0);
          expect
            .soft(overflow.panel, `${width}px: nothing overflows the panel`)
            .toBeLessThanOrEqual(0);
        }
        for (const t of targets)
          expect.soft(t.h, `${width}px: ${t.id} height`).toBeGreaterThanOrEqual(43.5);
      }
    }
    // Contrast of the citation and of uncited rows on the real page.
    await page.setViewportSize(DESKTOP);
    results["x8 contrast citation"] = await contrastRatio(page.getByTestId("ask-citation").first());
    results["x8 contrast uncited row"] = await contrastRatio(
      page.getByTestId("ask-passage").nth(1),
    );
  });
});

// ---------------------------------------------------------------------------------------------
// X9 The chat model dies in the middle of an answer
// ---------------------------------------------------------------------------------------------

test("X9: the chat model stops after the first delta: friendly error, no partial text, passages stay, retry works after the restart", async ({
  browser,
}) => {
  try {
    await withSession(browser, fx.thao, async (page) => {
      const seen = watch(page);
      await openAskPanel(page, fx.ws, fx.handbook.id);
      await clickAsk(
        page,
        "Explain in detail all the leave types in the policy: annual, marriage and bereavement.",
      );
      await expect
        .poll(
          async () =>
            (
              await page
                .getByTestId("ask-answer")
                .innerText()
                .catch(() => "")
            ).length,
          {
            timeout: 300_000,
          },
        )
        .toBeGreaterThan(5);
      stopService(CHAT_SERVICE);
      const state = await settle(page, 300_000);
      results["x9 state after the chat model stopped mid-answer"] = {
        state,
        error: await page
          .getByTestId("ask-error")
          .innerText()
          .catch(() => null),
        answerBoxes: await page.getByTestId("ask-answer").count(),
        passages: (await passageRows(page)).length,
        problems: seen.problems,
      };
      await page.screenshot({
        path: path.join(SCREENSHOTS_37, "x9-after-model-stop.png"),
        fullPage: true,
      });
      if (state === "error") {
        expect(await page.getByTestId("ask-answer").count(), "partial answer removed").toBe(0);
        expect(await page.getByTestId("ask-passages").count(), "passages stay").toBe(1);
      }
    });
  } finally {
    startService(CHAT_SERVICE);
    await waitAskWorks(fx.thao, fx.ws, fx.handbook.id);
  }
});
