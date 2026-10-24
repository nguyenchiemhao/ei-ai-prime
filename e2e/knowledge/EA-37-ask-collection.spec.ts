// EA-37 (KB-06): RAG answers with citations, strict mode and the "Ask this collection" panel. FAST tier:
// black-box specs written from .work/EA-37/contract.md and ticket.md only. Nothing here needs the chat model:
//  - the API checks use empty collections (no passages -> `done not_found` without a model call), or fail
//    before the stream (401/403/404/422);
//  - the UI checks answer the ask route with a stand-in (page.route): exact stream frames of the contract, or a
//    timed stream from a local SSE server (AC5 behaviour without a model).
// The model services decide one thing: when both the embedding model and the chat model are up, the
// empty-collection asks end with `done not_found`; when one is not, they end with 503 `model_unavailable` (both
// branches are asserted, the spec picks the branch itself). Runs against a running, migrated and seeded stack:
//   npm run up && npm run seed && npm run e2e -- e2e/knowledge/EA-37-ask-collection.spec.ts
// The real-model cases are in ...-slow.spec.ts (AC1-AC4, AC6, AC7, NFR, attacks) and ...-perf.spec.ts (AC5).
// Data: seeded accounts; every collection is named `qa-EA37-<run> ...`; seed rows are never changed. afterAll
// deletes everything and proves the row counts equal the counts before the run.
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import { expect, test } from "@playwright/test";
import { ADMIN, DESKTOP, contrastRatio, peopleOpsId, rows, watch } from "../support/ea22";
import { withSession } from "../support/ea23";
import { withoutStatuses, type CollectionItem } from "../support/ea32";
import { SONGHAN_ORG, apiOf } from "../support/ea33";
import {
  ANSWERED_EN,
  DEMO_ORG,
  EXISTING,
  LEAVE_PASSAGES,
  NOT_FOUND,
  Q,
  SCREENSHOTS_37,
  TXT,
  answerDoneLines,
  answerText,
  ask,
  cleanup37,
  clickAsk,
  counts37,
  expectJsonError,
  expectStream,
  headerNamesOf,
  makeCollection,
  markerRows37,
  modelsUp,
  mockJson,
  mockNetworkError,
  mockSse,
  observeAnswer,
  openAskPanel,
  passageRows,
  readAnswerLog,
  routeToFake,
  settle,
  setQuestion,
  squash,
  startFakeAsk,
  type Counts37,
  type SseEvent,
} from "../support/ea37";
import type { ApiSession } from "../support/ea22";

test.describe.configure({ mode: "default", timeout: 180_000 });

let baseline: Counts37 | undefined;
let ws = "";
/** Both the embedding model and the chat model are up (the route answers 503 model_unavailable when either is not). */
let embeddingUp = false;
let linh: ApiSession;
let thao: ApiSession;
let minh: ApiSession;
let son: ApiSession;
let ha: ApiSession;
let ngan: ApiSession;
/** Empty collections: restricted [managers], authenticated, public (People Ops). */
let restricted: CollectionItem;
let authenticated: CollectionItem;
let publicCol: CollectionItem;
/** Collections of other scopes (cross-Workspace and cross-Organization bait). */
let engineering: CollectionItem;
let songhan: CollectionItem;
let engWs = "";
let shWs = "";

const AUTH = { kind: "authenticated", groups: [] as string[] };
const askBody = (question: unknown, principal: unknown = AUTH): unknown => ({
  question,
  principal,
});

test.beforeAll(async () => {
  await cleanup37();
  baseline = counts37();
  ws = peopleOpsId();
  linh = await apiOf("linh");
  thao = await apiOf("thao");
  minh = await apiOf("minh");
  son = await apiOf("son");
  ha = await apiOf("ha");
  ngan = await apiOf("ngan");
  const quang = await apiOf("quang");
  embeddingUp = modelsUp();
  restricted = await makeCollection(linh, ws, "Bare Restricted", "restricted", ["managers"]);
  authenticated = await makeCollection(linh, ws, "Bare Authenticated", "authenticated");
  publicCol = await makeCollection(linh, ws, "Bare Public", "public");
  engWs = rows(
    `select id from workspaces where org_id = '${DEMO_ORG}' and name = 'Engineering'`,
  )[0] as string;
  shWs = rows(
    `select id from workspaces where org_id = '${SONGHAN_ORG}' and name = 'Customer Care'`,
  )[0] as string;
  expect(
    engWs && shWs,
    "precondition: Engineering and Customer Care Workspaces exist",
  ).toBeTruthy();
  engineering = await makeCollection(quang, engWs, "Bare Engineering", "public");
  songhan = await makeCollection(ngan, shWs, "Bare Songhan", "public");
});

test.afterAll(async () => {
  await cleanup37();
  if (baseline) expect(counts37(), "rows left behind").toEqual(baseline);
  expect(markerRows37(), "rows with the EA-37 marker left behind").toEqual([]);
});

function note(description: string): void {
  test.info().annotations.push({ type: "observation", description });
}

// ---------------------------------------------------------------------------------------------
// AC8 Matches design: the panel (no model needed)
// ---------------------------------------------------------------------------------------------

test("AC8: the Ask this collection panel matches the CollectionDetail artboard (texts, order, controls, styles)", async ({
  browser,
}) => {
  fs.mkdirSync(SCREENSHOTS_37, { recursive: true });
  await withSession(browser, thao, async (page) => {
    const seen = watch(page);
    await openAskPanel(page, ws, restricted.id);
    const panel = page.getByTestId("ask-panel");

    // Structure: a section with an h2 and the helper text, below the documents area.
    expect(await panel.evaluate((el) => el.tagName)).toBe("SECTION");
    const heading = panel.getByRole("heading", { level: 2, name: TXT.en.heading, exact: true });
    await expect(heading).toBeVisible();
    await expect(panel.getByText(TXT.en.helper, { exact: true })).toBeVisible();
    const foldersBox = await page.getByTestId("folders-panel").boundingBox();
    const panelBox = await panel.boundingBox();
    expect(foldersBox && panelBox, "boxes").toBeTruthy();
    expect(
      (panelBox?.y ?? 0) + 1,
      "the panel is below the folders / documents area",
    ).toBeGreaterThanOrEqual((foldersBox?.y ?? 0) + (foldersBox?.height ?? 0));

    // Ask as: label, two options, default Signed-in user.
    const principal = page.getByTestId("ask-principal");
    // The select sits inside its label, so getByLabel would also match the option texts: use the accessible name.
    await expect(
      panel.getByRole("combobox", { name: TXT.en.principalLabel, exact: true }),
    ).toHaveAttribute("data-testid", "ask-principal");
    expect(await principal.evaluate((el) => el.tagName)).toBe("SELECT");
    const options = await principal
      .locator("option")
      .evaluateAll((all) =>
        all.map((o) => [(o as HTMLOptionElement).value, (o.textContent ?? "").trim()]),
      );
    expect(options.slice().sort()).toEqual(
      [
        ["anonymous", TXT.en.anonymous],
        ["authenticated", TXT.en.signedIn],
      ].sort(),
    );
    await expect(principal).toHaveValue("authenticated");

    // Groups: only for Signed-in user, prefilled with the collection's groups, with its help text.
    const groups = page.getByTestId("ask-groups");
    await expect(panel.getByLabel(TXT.en.groupsLabel, { exact: true })).toHaveAttribute(
      "data-testid",
      "ask-groups",
    );
    expect((await groups.inputValue()).split(",").map((g) => g.trim())).toEqual(["managers"]);
    await expect(panel.getByText(TXT.en.groupsHelp, { exact: true })).toBeVisible();

    // Question row: hidden label, placeholder, limit, button disabled while blank.
    const question = page.getByTestId("ask-question");
    await expect(panel.getByLabel(TXT.en.questionLabel, { exact: true })).toHaveAttribute(
      "data-testid",
      "ask-question",
    );
    // The label may wrap the input; the label TEXT is what must be visually hidden.
    const labelText = panel.getByText(TXT.en.questionLabel, { exact: true });
    expect(await question.evaluate((el) => (el as HTMLInputElement).labels?.length)).toBe(1);
    const labelBox = await labelText.boundingBox();
    expect(
      Math.min(labelBox?.width ?? -1, labelBox?.height ?? -1),
      "the label text is visually hidden",
    ).toBeLessThanOrEqual(1);
    await expect(question).toHaveAttribute("placeholder", TXT.en.placeholder);
    await expect(question).toHaveAttribute("maxlength", "2000");
    const submit = page.getByTestId("ask-submit");
    await expect(submit).toHaveText(TXT.en.submit);
    await expect(submit).toBeDisabled();

    // Order and layout: heading < helper < Ask-as row < question row; input and button on one row.
    const y = async (testId: string): Promise<number> =>
      (await page.getByTestId(testId).boundingBox())?.y ?? Number.NaN;
    const headingY = (await heading.boundingBox())?.y ?? Number.NaN;
    expect(headingY).toBeLessThan(await y("ask-principal"));
    expect(await y("ask-principal")).toBeLessThan(await y("ask-question"));
    expect(
      Math.abs((await y("ask-principal")) - (await y("ask-groups"))),
      "Ask as and Groups share the row above the question",
    ).toBeLessThan(40);
    const q = await question.boundingBox();
    const b = await submit.boundingBox();
    expect(q && b).toBeTruthy();
    expect(
      Math.abs((q?.y ?? 0) + (q?.height ?? 0) / 2 - ((b?.y ?? 0) + (b?.height ?? 0) / 2)),
    ).toBeLessThan(4);
    expect(b?.x ?? 0, "button to the right of the input").toBeGreaterThan(
      (q?.x ?? 0) + (q?.width ?? 0) - 1,
    );
    expect(q?.height ?? 0, "input height 44px").toBeGreaterThanOrEqual(43.5);
    expect(q?.height ?? 0).toBeLessThanOrEqual(45);
    expect(b?.height ?? 0, "button min-height 44px").toBeGreaterThanOrEqual(43.5);
    expect(
      await question.evaluate(
        (el) =>
          !!el.closest("form")?.contains(document.querySelector('[data-testid="ask-submit"]')),
      ),
      "input and button are in one form",
    ).toBe(true);

    // Styles of the artboard.
    const css = async (testId: string) =>
      page.getByTestId(testId).evaluate((el) => {
        const s = getComputedStyle(el);
        return {
          bg: s.backgroundColor,
          color: s.color,
          radius: s.borderTopLeftRadius,
          border: `${s.borderTopWidth} ${s.borderTopColor}`,
          padding: s.padding,
          size: s.fontSize,
          weight: s.fontWeight,
        };
      });
    const panelCss = await css("ask-panel");
    expect.soft(panelCss).toMatchObject({
      bg: "rgb(255, 255, 255)",
      radius: "12px",
      padding: "20px",
      border: "1px rgb(225, 228, 232)",
    });
    const h2 = await heading.evaluate((el) => {
      const s = getComputedStyle(el);
      return { size: s.fontSize, weight: s.fontWeight };
    });
    expect.soft(h2).toEqual({ size: "16px", weight: "600" });
    const helper = await panel.getByText(TXT.en.helper, { exact: true }).evaluate((el) => {
      const s = getComputedStyle(el);
      return { size: s.fontSize, color: s.color };
    });
    expect.soft(helper).toEqual({ size: "13px", color: "rgb(85, 94, 107)" });
    expect.soft(await css("ask-question")).toMatchObject({
      radius: "8px",
      size: "14px",
      border: "1px rgb(138, 146, 156)",
    });
    expect.soft(await css("ask-submit")).toMatchObject({
      bg: "rgb(35, 70, 199)",
      color: "rgb(255, 255, 255)",
      radius: "8px",
      size: "14px",
      weight: "600",
    });
    await panel.screenshot({ path: `${SCREENSHOTS_37}/ac8-panel-en.png` });

    // Groups: empty when the collection is not Restricted.
    await openAskPanel(page, ws, authenticated.id);
    await expect(page.getByTestId("ask-groups")).toHaveValue("");
    await openAskPanel(page, ws, publicCol.id);
    await expect(page.getByTestId("ask-groups")).toHaveValue("");
    expect(withoutStatuses(seen.problems, [])).toEqual([]);
  });
});

test("AC8 TC-8-2: the console stays English whatever the browser language (no language switch in this release); the answer-language texts follow the question", async ({
  browser,
}) => {
  // Contract: the Vietnamese UI texts are checked by component tests and in the vi catalog, not in the browser.
  // What can be seen from outside: with a Vietnamese browser the panel is still English, and the not-found
  // message / no-passages text follow their own rules (question language / console language).
  const context = await browser.newContext({ locale: "vi-VN", viewport: DESKTOP });
  try {
    await context.addCookies([...thao.jar].map(([name, value]) => ({ name, value, url: ADMIN })));
    const page = await context.newPage();
    await openAskPanel(page, ws, restricted.id);
    const panel = page.getByTestId("ask-panel");
    await expect(panel.getByRole("heading", { level: 2, name: TXT.en.heading })).toBeVisible();
    await expect(panel.getByText(TXT.en.helper, { exact: true })).toBeVisible();
    await expect(page.getByTestId("ask-submit")).toHaveText(TXT.en.submit);
    await expect(page.getByTestId("ask-question")).toHaveAttribute(
      "placeholder",
      TXT.en.placeholder,
    );
    // A Vietnamese question: the not-found message is Vietnamese, the console texts stay English.
    await mockSse(page, [
      ["passages", { language: "vi", passages: LEAVE_PASSAGES.slice(0, 1) }],
      ["done", { outcome: "not_found", answer: "", citations: [] }],
    ]);
    await clickAsk(page, "Giá cổ phiếu của công ty hôm nay là bao nhiêu?");
    expect(await settle(page, 15_000)).toBe("not_found");
    expect(await answerText(page)).toBe(NOT_FOUND.vi);
    await expect(page.getByTestId("ask-passages")).toContainText(TXT.en.passages);
    await page.unroute("**/api/workspaces/*/collections/*/ask");
    await mockSse(page, [
      ["passages", { language: "vi", passages: [] }],
      ["done", { outcome: "not_found", answer: "", citations: [] }],
    ]);
    await clickAsk(page, "Giá cổ phiếu của công ty hôm nay là bao nhiêu?");
    await expect(page.getByTestId("ask-no-passages")).toHaveText(TXT.en.noPassages);
  } finally {
    await context.close();
  }
});

test("AC8 TC-8-3: keyboard and basics: labels, Tab order, Enter submits, blank disables, one request per ask", async ({
  browser,
}) => {
  await withSession(browser, thao, async (page) => {
    const recorded = await mockSse(page, ANSWERED_EN);
    await openAskPanel(page, ws, restricted.id);
    const submit = page.getByTestId("ask-submit");
    const question = page.getByTestId("ask-question");
    await expect(submit).toBeDisabled();
    await question.fill("   ");
    await expect(submit, "whitespace only is blank").toBeDisabled();
    await question.fill("x");
    await expect(submit).toBeEnabled();
    await question.fill("");
    await expect(submit).toBeDisabled();
    expect(recorded, "nothing is sent while typing").toHaveLength(0);

    // Tab order: Ask as -> Groups -> Test question -> Ask.
    await page.getByTestId("ask-principal").focus();
    await page.keyboard.press("Tab");
    await expect(page.getByTestId("ask-groups")).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(question).toBeFocused();
    await page.keyboard.type(Q.marryEn);
    await page.keyboard.press("Tab");
    await expect(submit).toBeFocused();

    // Enter in the input asks once.
    await question.focus();
    await page.keyboard.press("Enter");
    expect(await settle(page, 15_000)).toBe("answered");
    expect(recorded).toHaveLength(1);
    // The focus is not trapped: the input keeps its text and can be edited.
    await expect(question).toHaveValue(Q.marryEn);
    // The error alert is announced: role=alert (checked in AC7 TC-7-1).
  });
});

test("AC8 TC-8-4: answer box, citations and passage rows use the artboard styles (rendered from a stream)", async ({
  browser,
}) => {
  await withSession(browser, thao, async (page) => {
    await mockSse(page, ANSWERED_EN);
    await openAskPanel(page, ws, authenticated.id);
    await clickAsk(page, Q.marryEn);
    expect.soft(await settle(page, 15_000)).toBe("answered");
    const box = await page.getByTestId("ask-answer").evaluate((el) => {
      const s = getComputedStyle(el);
      return {
        bg: s.backgroundColor,
        radius: s.borderTopLeftRadius,
        padding: s.padding,
        size: s.fontSize,
        line: s.lineHeight,
      };
    });
    expect.soft(box).toEqual({
      bg: "rgb(246, 247, 248)",
      radius: "10px",
      padding: "14px 16px",
      size: "14px",
      line: "22.4px",
    });
    const citation = page.getByTestId("ask-citation").first();
    const citationCss = await citation.evaluate((el) => {
      const s = getComputedStyle(el);
      return { color: s.color, size: s.fontSize, weight: s.fontWeight };
    });
    expect.soft(citationCss).toEqual({ color: "rgb(11, 107, 92)", size: "12px", weight: "600" });
    expect
      .soft(await contrastRatio(citation), "teal [n] on the grey box")
      .toBeGreaterThanOrEqual(4.5);

    const list = page.getByTestId("ask-passages");
    const title = list.getByText(TXT.en.passages, { exact: true });
    expect
      .soft(
        await title.evaluate((el) => {
          const s = getComputedStyle(el);
          return { size: s.fontSize, weight: s.fontWeight, color: s.color };
        }),
      )
      .toEqual({ size: "12px", weight: "600", color: "rgb(85, 94, 107)" });
    const rowsLoc = page.getByTestId("ask-passage");
    const cited = rowsLoc.nth(0);
    const uncited = rowsLoc.nth(1);
    expect.soft(await cited.evaluate((el) => getComputedStyle(el).fontSize)).toBe("13px");
    const number = cited.getByText("[1]", { exact: true });
    expect
      .soft(
        await number.evaluate((el) => {
          const s = getComputedStyle(el);
          return { color: s.color, weight: s.fontWeight };
        }),
      )
      .toEqual({ color: "rgb(11, 107, 92)", weight: "600" });
    expect
      .soft(
        await uncited.evaluate((el) => getComputedStyle(el).color),
        "uncited rows use the secondary text colour",
      )
      .toBe("rgb(85, 94, 107)");
    expect
      .soft(await contrastRatio(uncited), "secondary text on white")
      .toBeGreaterThanOrEqual(4.5);
    const mono = await uncited
      .getByTestId("ask-passage-score")
      .evaluate((el) => getComputedStyle(el).fontFamily);
    expect.soft(mono, "scores are monospace").toMatch(/mono/i);
    const sourceBox = await uncited.getByTestId("ask-passage-source").boundingBox();
    const scoreBox = await uncited.getByTestId("ask-passage-score").boundingBox();
    expect
      .soft(scoreBox?.x ?? 0, "the score is to the right of the source")
      .toBeGreaterThan(sourceBox?.x ?? 0);
    expect
      .soft(Math.abs((scoreBox?.y ?? 0) - (sourceBox?.y ?? 0)), "source and score share a line")
      .toBeLessThan(8);
    await page
      .getByTestId("ask-panel")
      .screenshot({ path: `${SCREENSHOTS_37}/ac8-answered-en.png` });
  });
});

// ---------------------------------------------------------------------------------------------
// AC1 / AC2 / AC3 / AC4: how the UI renders the contract's stream
// ---------------------------------------------------------------------------------------------

test("AC1 TC-1-3: an answered stream shows the answer with inline [n] and the passages list (title · section, score, cited flag)", async ({
  browser,
}) => {
  await withSession(browser, thao, async (page) => {
    const seen = watch(page);
    await mockSse(page, ANSWERED_EN);
    await openAskPanel(page, ws, authenticated.id);
    await clickAsk(page, Q.marryEn);
    expect(await settle(page, 15_000)).toBe("answered");
    const answer = page.getByTestId("ask-answer");
    await expect(answer).toHaveAttribute("data-outcome", "answered");
    await expect(answer).toHaveAttribute("data-language", "en");
    await expect(answer).not.toHaveAttribute("aria-busy", "true");
    const text = await answerText(page);
    expect(text).toContain("Employees get 3 days of fully paid leave when they marry");
    await expect(page.getByTestId("ask-citation")).toHaveCount(1);
    await expect(page.getByTestId("ask-citation").first()).toHaveText("[1]");
    await expect(answer.getByTestId("ask-citation")).toHaveCount(1);

    const list = page.getByTestId("ask-passages");
    await expect(list).toBeVisible();
    await expect(list).toContainText(TXT.en.passages);
    const found = await passageRows(page);
    expect(found.map((r) => [r.number, r.cited, r.source, r.score])).toEqual([
      ["1", true, "Leave Policy 2026 · §4.1 Personal leave", "0.61"],
      ["2", false, "Leave Policy 2026 · §4.3 Bereavement leave", "0.49"],
      ["3", false, "Office Hours · Opening hours", "0.31"],
    ]);
    expect(found[0]?.text, "the number is shown for the cited row").toMatch(/\[1\]/);
    for (const row of found.slice(1)) {
      expect(row.text, "the number is not shown for uncited rows").not.toMatch(/\[\d+\]/);
    }
    await expect(page.getByTestId("ask-no-passages")).toHaveCount(0);
    await expect(page.getByTestId("ask-error")).toHaveCount(0);
    await expect(page.getByTestId("ask-submit")).toBeEnabled();
    expect(withoutStatuses(seen.problems, [])).toEqual([]);

    // A page number shows as " · p. N" (a null section is not asserted: the contract does not say).
    await page.unroute("**/api/workspaces/*/collections/*/ask");
    await mockSse(page, [
      [
        "passages",
        {
          language: "en",
          passages: [{ number: 1, title: "Handbook", section: "Overview", page: 12, score: 0.9 }],
        },
      ],
      ["delta", { text: "See the handbook [1]." }],
      ["done", { outcome: "answered", answer: "See the handbook [1].", citations: [1] }],
    ]);
    await clickAsk(page, "handbook?");
    expect(await settle(page, 15_000)).toBe("answered");
    expect((await passageRows(page))[0]?.source).toBe(
      `Handbook · Overview · ${TXT.en.pageSuffix} 12`,
    );

    // A passage without a section: "Title" only, or "Title · p. N" when a page is known.
    await page.unroute("**/api/workspaces/*/collections/*/ask");
    await mockSse(page, [
      [
        "passages",
        {
          language: "en",
          passages: [
            { number: 1, title: "Plain Title", section: null, page: null, score: 0.8 },
            { number: 2, title: "Scanned Doc", section: null, page: 7, score: 0.5 },
            { number: 3, title: "Full Doc", section: "§1 Intro", page: 3, score: 0.4 },
          ],
        },
      ],
      ["delta", { text: "Answer [2]." }],
      ["done", { outcome: "answered", answer: "Answer [2].", citations: [2] }],
    ]);
    await clickAsk(page, "null section?");
    expect(await settle(page, 15_000)).toBe("answered");
    const nulls = await passageRows(page);
    expect(nulls.map((r) => [r.number, r.cited, r.source])).toEqual([
      ["1", false, "Plain Title"],
      ["2", true, `Scanned Doc · ${TXT.en.pageSuffix} 7`],
      ["3", false, `Full Doc · §1 Intro · ${TXT.en.pageSuffix} 3`],
    ]);
    expect(nulls[1]?.text, "cited row shows [2] with brackets").toContain("[2]");
    expect(nulls[0]?.text, "uncited row shows no [n]").not.toMatch(/\[\d+\]/);
    expect(nulls[0]?.text, "uncited row starts with the title").toMatch(/^Plain Title/);
  });
});

test("AC1 TC-1-6: the UI sends only the question and the principal (no identity fields); Enter and the button both ask", async ({
  browser,
}) => {
  await withSession(browser, thao, async (page) => {
    const recorded = await mockSse(page, ANSWERED_EN);
    await openAskPanel(page, ws, restricted.id);
    await setQuestion(page, `  ${Q.marryVi}  `);
    await page.getByTestId("ask-question").press("Enter");
    expect(await settle(page, 15_000)).toBe("answered");
    await clickAsk(page, Q.marryEn);
    await expect.poll(() => recorded.length).toBe(2);
    for (const call of recorded) {
      const body = call.body as { question: string; principal: Record<string, unknown> };
      expect(
        Object.keys(body).sort(),
        "no org_id, user_id or workspace_id from the client",
      ).toEqual(["principal", "question"]);
      expect(Object.keys(body.principal).sort()).toEqual(["groups", "kind"]);
      expect(call.headers["x-csrf-token"], "CSRF token sent").toBeTruthy();
      expect(call.headers["content-type"]).toMatch(/application\/json/);
      expect(new URL(call.url).pathname).toBe(
        `/api/workspaces/${ws}/collections/${restricted.id}/ask`,
      );
    }
    expect((recorded[0]?.body as { question: string }).question.trim()).toBe(Q.marryVi);
    expect((recorded[1]?.body as { question: string }).question.trim()).toBe(Q.marryEn);
  });
});

test("AC1 TC-1-8: the answer and the passage titles are plain text (HTML and Markdown in them are not rendered)", async ({
  browser,
}) => {
  await withSession(browser, thao, async (page) => {
    const evil = '<img src=x onerror="window.__xss=1"> **bold** <b>b</b> [1]';
    await mockSse(page, [
      [
        "passages",
        {
          language: "en",
          passages: [
            {
              number: 1,
              title: "<i>Policy</i>",
              section: "<script>window.__xss=2</script>",
              page: null,
              score: 0.5,
            },
          ],
        },
      ],
      ["delta", { text: evil }],
      ["done", { outcome: "answered", answer: evil, citations: [1] }],
    ]);
    await openAskPanel(page, ws, authenticated.id);
    await clickAsk(page, "test");
    expect(await settle(page, 15_000)).toBe("answered");
    expect(
      await page.evaluate(() => (window as unknown as { __xss?: number }).__xss),
    ).toBeUndefined();
    const answer = page.getByTestId("ask-answer");
    await expect(answer.locator("img")).toHaveCount(0);
    await expect(answer.locator("b")).toHaveCount(0);
    expect(await answerText(page)).toContain('<img src=x onerror="window.__xss=1">');
    expect(await answerText(page)).toContain("**bold**");
    await expect(page.getByTestId("ask-passages").locator("i, script")).toHaveCount(0);
    expect((await passageRows(page))[0]?.source).toBe(
      "<i>Policy</i> · <script>window.__xss=2</script>",
    );
  });
});

test("AC2 TC-2-2: when done arrives the streamed text is replaced by the final answer (no uncited guess, no invalid [n] stays)", async ({
  browser,
}) => {
  await withSession(browser, thao, async (page) => {
    // answered: the deltas held an invalid number and a guess; done.answer is the checked text.
    await mockSse(page, [
      ["passages", { language: "en", passages: LEAVE_PASSAGES }],
      ["delta", { text: "Maybe 5 days [7]" }],
      ["delta", { text: " or 9 [3]" }],
      [
        "done",
        {
          outcome: "answered",
          answer: "Employees get 3 days of fully paid leave when they marry [1].",
          citations: [1],
        },
      ],
    ]);
    await openAskPanel(page, ws, authenticated.id);
    await clickAsk(page, Q.marryEn);
    expect(await settle(page, 15_000)).toBe("answered");
    const text = await answerText(page);
    expect(text).not.toContain("Maybe");
    expect(text).not.toContain("[7]");
    expect(text).not.toContain("[3]");
    expect(text).toContain("3 days of fully paid leave");
    await expect(page.getByTestId("ask-citation")).toHaveCount(1);

    // not_found after a streamed guess: the guess disappears, the not-found message shows.
    await page.unroute("**/api/workspaces/*/collections/*/ask");
    await mockSse(page, [
      ["passages", { language: "en", passages: LEAVE_PASSAGES }],
      ["delta", { text: "I guess the capital is Sydney [2]" }],
      ["done", { outcome: "not_found", answer: "", citations: [] }],
    ]);
    await clickAsk(page, "What is the capital of Australia?");
    expect(await settle(page, 15_000)).toBe("not_found");
    const notFound = await answerText(page);
    expect(notFound).not.toContain("Sydney");
    expect(notFound).not.toContain("[2]");
    expect(notFound).toBe(NOT_FOUND.en);
    await expect(page.getByTestId("ask-citation")).toHaveCount(0);
  });
});

test("AC3 TC-3-3: not_found shows the message in the QUESTION's language (en and vi) with all passages uncited; no passages shows the no-passages text", async ({
  browser,
}) => {
  await withSession(browser, thao, async (page) => {
    const events = (language: "en" | "vi"): SseEvent[] => [
      ["passages", { language, passages: LEAVE_PASSAGES.slice(0, 2) }],
      ["done", { outcome: "not_found", answer: "", citations: [] }],
    ];
    await openAskPanel(page, ws, authenticated.id);
    for (const language of ["en", "vi"] as const) {
      await page.unroute("**/api/workspaces/*/collections/*/ask").catch(() => undefined);
      await mockSse(page, events(language));
      await clickAsk(
        page,
        language === "en" ? "What is the capital of Australia?" : "Giá cổ phiếu?",
      );
      expect(await settle(page, 15_000)).toBe("not_found");
      const answer = page.getByTestId("ask-answer");
      await expect(answer).toHaveAttribute("data-outcome", "not_found");
      await expect(answer).toHaveAttribute("data-language", language);
      expect(await answerText(page), `console is English, question is ${language}`).toBe(
        NOT_FOUND[language],
      );
      await expect(page.getByTestId("ask-citation")).toHaveCount(0);
      await expect(page.getByTestId("ask-passages")).toBeVisible();
      const found = await passageRows(page);
      expect(found).toHaveLength(2);
      for (const row of found) {
        expect(row.cited).toBe(false);
        expect(row.text).not.toMatch(/\[\d+\]/);
      }
      await expect(page.getByTestId("ask-no-passages")).toHaveCount(0);
    }

    // Nothing found at all.
    await page.unroute("**/api/workspaces/*/collections/*/ask");
    await mockSse(page, [
      ["passages", { language: "en", passages: [] }],
      ["done", { outcome: "not_found", answer: "", citations: [] }],
    ]);
    await clickAsk(page, "What is the capital of Australia?");
    expect(await settle(page, 15_000)).toBe("not_found");
    await expect(page.getByTestId("ask-answer")).toHaveAttribute("data-outcome", "not_found");
    await expect(page.getByTestId("ask-no-passages")).toHaveText(TXT.en.noPassages);
    await expect(page.getByTestId("ask-passages")).toHaveCount(0);
    expect(await answerText(page), "no not-found text next to the no-passages text").not.toContain(
      NOT_FOUND.en,
    );
  });
});

test("AC4 TC-4-4: the answer box carries the question's language (data-language) and keeps Vietnamese diacritics intact", async ({
  browser,
}) => {
  await withSession(browser, thao, async (page) => {
    const answer = "Nhân viên được nghỉ 3 ngày hưởng nguyên lương khi kết hôn [1].";
    await mockSse(page, [
      ["passages", { language: "vi", passages: LEAVE_PASSAGES }],
      ["delta", { text: answer }],
      ["done", { outcome: "answered", answer, citations: [1] }],
    ]);
    await openAskPanel(page, ws, authenticated.id);
    await clickAsk(page, Q.marryVi);
    expect(await settle(page, 15_000)).toBe("answered");
    await expect(page.getByTestId("ask-answer")).toHaveAttribute("data-language", "vi");
    expect(await answerText(page)).toBe(answer);
    await expect(page.getByTestId("ask-citation")).toHaveText("[1]");
  });
});

// ---------------------------------------------------------------------------------------------
// AC5 Streaming behaviour (timed stream from a local server; no model)
// ---------------------------------------------------------------------------------------------

test("AC5 TC-5-3: the answer grows while answering (aria-busy, button disabled), then settles on the final answer", async ({
  browser,
}) => {
  const fake = await startFakeAsk();
  try {
    await withSession(browser, thao, async (page) => {
      await observeAnswer(page);
      await routeToFake(page, fake);
      fake.script([
        { event: "passages", data: { language: "en", passages: LEAVE_PASSAGES } },
        { afterMs: 500, event: "delta", data: { text: "Employees get " } },
        { afterMs: 600, event: "delta", data: { text: "3 days of fully paid leave " } },
        { afterMs: 600, event: "delta", data: { text: "when they marry " } },
        { afterMs: 600, event: "delta", data: { text: "[1]" } },
        { afterMs: 600, event: "delta", data: { text: "." } },
        {
          afterMs: 300,
          event: "done",
          data: {
            outcome: "answered",
            answer: "Employees get 3 days of fully paid leave when they marry [1].",
            citations: [1],
          },
        },
      ]);
      await openAskPanel(page, ws, authenticated.id);
      await clickAsk(page, Q.marryEn);
      const answer = page.getByTestId("ask-answer");
      await expect(answer).toHaveAttribute("data-outcome", "answering");
      await expect(answer).toHaveAttribute("aria-busy", "true");
      await expect(page.getByTestId("ask-submit"), "disabled while answering").toBeDisabled();
      // Contract: there is no "ask again while answering": Enter in the input does nothing.
      await page.getByTestId("ask-question").press("Enter");
      await page
        .getByTestId("ask-submit")
        .click({ force: true, timeout: 2000 })
        .catch(() => undefined);
      expect(fake.bodies, "Enter / click while answering send no second request").toHaveLength(1);
      expect(await settle(page, 20_000)).toBe("answered");
      await expect(answer).not.toHaveAttribute("aria-busy", "true");
      await expect(page.getByTestId("ask-submit")).toBeEnabled();

      const { clickAt, samples } = await readAnswerLog(page);
      expect(clickAt, "the click was observed").toBeGreaterThan(0);
      const whileAnswering = samples.filter((s) => s.outcome === "answering");
      expect(whileAnswering.length).toBeGreaterThan(0);
      expect(
        whileAnswering.every((s) => s.busy === "true"),
        "aria-busy=true during the whole answering state",
      ).toBe(true);
      const texts = [...new Set(whileAnswering.map((s) => s.text).filter((t) => t !== ""))];
      expect(
        texts.length,
        `different non-empty texts while answering: ${JSON.stringify(texts)}`,
      ).toBeGreaterThanOrEqual(2);
      for (let i = 1; i < texts.length; i += 1) {
        expect((texts[i] as string).length, "the text only grows").toBeGreaterThanOrEqual(
          (texts[i - 1] as string).length,
        );
      }
      const first = whileAnswering.find((s) => s.text !== "");
      note(
        `first visible text ${Math.round((first?.t ?? 0) - clickAt)} ms after the click (stand-in server: 500 ms first delta)`,
      );
      expect(fake.bodies).toHaveLength(1);
      expect(Object.keys(fake.bodies[0] as object).sort()).toEqual(["principal", "question"]);

      // Asking again replaces the whole previous answer and its passages (no leftovers).
      fake.script([
        { event: "passages", data: { language: "en", passages: [LEAVE_PASSAGES[2]] } },
        { afterMs: 200, event: "delta", data: { text: "Open from 8:00 [1]." } },
        {
          afterMs: 200,
          event: "done",
          data: { outcome: "answered", answer: "Open from 8:00 [1].", citations: [1] },
        },
      ]);
      await clickAsk(page, Q.officeEn);
      await expect(answer).toContainText("Open from 8:00");
      expect(await settle(page, 20_000)).toBe("answered");
      expect(await answerText(page)).toBe("Open from 8:00 [1].");
      expect(await passageRows(page)).toHaveLength(1);
      await expect(page.getByTestId("ask-citation")).toHaveCount(1);
    });
  } finally {
    await fake.close();
  }
});

test("AC5 TC-5-4: leaving the page while an answer streams closes the request", async ({
  browser,
}) => {
  const fake = await startFakeAsk();
  try {
    await withSession(browser, thao, async (page) => {
      await routeToFake(page, fake);
      fake.script([
        { event: "passages", data: { language: "en", passages: LEAVE_PASSAGES } },
        { afterMs: 300, event: "delta", data: { text: "Employees get " } },
        { afterMs: 60_000, event: "delta", data: { text: "never shown" } },
      ]);
      await openAskPanel(page, ws, authenticated.id);
      await clickAsk(page, Q.marryEn);
      await expect(page.getByTestId("ask-answer")).toContainText("Employees get");
      await page.goto(`/w/${ws}/knowledge`);
      await expect
        .poll(() => fake.aborted, {
          timeout: 15_000,
          message: "the stream was closed by the browser",
        })
        .toBeGreaterThanOrEqual(1);
    });
  } finally {
    await fake.close();
  }
});

// ---------------------------------------------------------------------------------------------
// AC6 Simulated access: the controls and what the UI sends
// ---------------------------------------------------------------------------------------------

test("AC6 TC-6-3: Ask as / Groups: Groups hides for Anonymous, the request carries kind + groups (never hidden groups), groups are split on commas", async ({
  browser,
}) => {
  await withSession(browser, thao, async (page) => {
    const recorded = await mockSse(page, [
      ["passages", { language: "en", passages: [] }],
      ["done", { outcome: "not_found", answer: "", citations: [] }],
    ]);
    await openAskPanel(page, ws, restricted.id);
    const groups = page.getByTestId("ask-groups");
    await expect(groups).toBeVisible();

    // Anonymous: Groups is hidden and the (prefilled) groups are NOT sent.
    await page.getByTestId("ask-principal").selectOption("anonymous");
    await expect(groups).not.toBeVisible();
    await clickAsk(page, Q.salaryEn);
    await settle(page, 15_000);
    expect(recorded[0]?.body).toEqual({
      question: Q.salaryEn,
      principal: { kind: "anonymous", groups: [] },
    });

    // Back to Signed-in user: Groups is back; edit and send.
    await page.getByTestId("ask-principal").selectOption("authenticated");
    await expect(groups).toBeVisible();
    await groups.fill("managers, hr ");
    await clickAsk(page, Q.salaryEn);
    await expect.poll(() => recorded.length).toBe(2);
    expect(recorded[1]?.body).toEqual({
      question: Q.salaryEn,
      principal: { kind: "authenticated", groups: ["managers", "hr"] },
    });

    // Groups emptied: an empty list.
    await groups.fill("");
    await clickAsk(page, Q.salaryEn);
    await expect.poll(() => recorded.length).toBe(3);
    expect((recorded[2]?.body as { principal: unknown }).principal).toEqual({
      kind: "authenticated",
      groups: [],
    });

    // Other access levels start with empty Groups and Signed-in user.
    for (const col of [authenticated.id, publicCol.id]) {
      await openAskPanel(page, ws, col);
      await expect(page.getByTestId("ask-groups")).toHaveValue("");
      await expect(page.getByTestId("ask-principal")).toHaveValue("authenticated");
    }
  });
});

// ---------------------------------------------------------------------------------------------
// AC7 Model error and error statuses in the UI
// ---------------------------------------------------------------------------------------------

test("AC7 TC-7-1: a 503, an error frame, a 5xx and a network failure all show the friendly message (role=alert), no technical details", async ({
  browser,
}) => {
  await withSession(browser, thao, async (page) => {
    await openAskPanel(page, ws, authenticated.id);
    const scenarios: { label: string; install: () => Promise<unknown> }[] = [
      { label: "503 JSON", install: () => mockJson(page, 503, { detail: "model_unavailable" }) },
      {
        label: "error frame model_unavailable",
        install: () =>
          mockSse(page, [
            ["passages", { language: "en", passages: LEAVE_PASSAGES }],
            ["error", { code: "model_unavailable" }],
          ]),
      },
      {
        label: "error frame answer_failed after a partial answer",
        install: () =>
          mockSse(page, [
            ["passages", { language: "en", passages: LEAVE_PASSAGES }],
            ["delta", { text: "Employees get " }],
            ["error", { code: "answer_failed" }],
          ]),
      },
      { label: "500 JSON", install: () => mockJson(page, 500, { detail: "internal_error" }) },
      {
        label: "502 HTML from a proxy",
        install: () =>
          page.route("**/api/workspaces/*/collections/*/ask", (route) =>
            route.fulfill({
              status: 502,
              contentType: "text/html",
              body: "<html><body><h1>502 Bad Gateway</h1><p>nginx</p></body></html>",
            }),
          ),
      },
      { label: "network failure", install: () => mockNetworkError(page) },
    ];
    for (const scenario of scenarios) {
      await page.unroute("**/api/workspaces/*/collections/*/ask");
      await scenario.install();
      await clickAsk(page, Q.marryEn);
      const error = page.getByTestId("ask-error");
      await expect(error, scenario.label).toBeVisible();
      await expect(error, scenario.label).toHaveAttribute("role", "alert");
      expect(squash(await error.innerText()), scenario.label).toBe(TXT.en.error);
      const body = await page.locator("body").innerText();
      expect(body, `${scenario.label}: no Traceback`).not.toMatch(
        /Traceback|Error:|nginx|Bad Gateway/,
      );
      expect(body, `${scenario.label}: no model name or status code in the panel`).not.toMatch(
        /qwen|bge-m3|model_unavailable|answer_failed|\b50[0-9]\b/i,
      );
      await expect(page.getByTestId("ask-submit"), `${scenario.label}: can retry`).toBeEnabled();
      // Contract: after an error the answer box (and any partial text) is gone; the passages already received stay.
      await expect(
        page.getByTestId("ask-answer"),
        `${scenario.label}: no answer box / partial text after an error`,
      ).toHaveCount(0);
      if (scenario.label.startsWith("error frame")) {
        await expect(
          page.getByTestId("ask-passages"),
          `${scenario.label}: the passages list already received stays visible`,
        ).toBeVisible();
        expect(await passageRows(page)).toHaveLength(LEAVE_PASSAGES.length);
      }
    }
    // After the failures a good answer clears the alert.
    await page.unroute("**/api/workspaces/*/collections/*/ask");
    await mockSse(page, ANSWERED_EN);
    await clickAsk(page, Q.marryEn);
    expect(await settle(page, 15_000)).toBe("answered");
    await expect(page.getByTestId("ask-error")).toHaveCount(0);
  });
});

test("AC7 TC-7-6: 404 shows Not found, 403 the no-permission message, invalid_group the Groups error", async ({
  browser,
}) => {
  await withSession(browser, thao, async (page) => {
    await openAskPanel(page, ws, restricted.id);
    await mockJson(page, 422, { detail: "invalid_group" });
    await page.getByTestId("ask-groups").fill("a".repeat(65));
    await clickAsk(page, Q.salaryEn);
    await expect(page.getByTestId("ask-groups-error")).toHaveText(EXISTING.invalidGroup);

    await page.unroute("**/api/workspaces/*/collections/*/ask");
    await mockJson(page, 403, { detail: "forbidden" });
    await openAskPanel(page, ws, restricted.id);
    await clickAsk(page, Q.salaryEn);
    await expect(page.getByText(EXISTING.forbidden).first()).toBeVisible();

    await page.unroute("**/api/workspaces/*/collections/*/ask");
    await mockJson(page, 404, { detail: "not_found" });
    await openAskPanel(page, ws, restricted.id);
    await clickAsk(page, Q.salaryEn);
    await expect(page.getByText(/not found/i).first()).toBeVisible();
  });
});

test("AC7 TC-7-7: a real expired session (cookie removed in the browser) sends the user to sign in", async ({
  browser,
}) => {
  await withSession(browser, thao, async (page, context) => {
    await openAskPanel(page, ws, restricted.id);
    await context.clearCookies({ name: "ei_session" });
    await clickAsk(page, Q.salaryEn);
    await expect(page, "a real 401 on ask sends the user to sign in").toHaveURL(/\/sign-in/, {
      timeout: 10_000,
    });
  });
});

// ---------------------------------------------------------------------------------------------
// API (no model): the route, its permissions, errors and validation
// ---------------------------------------------------------------------------------------------

test("AC1 TC-1-7: Knowledge Editor, Builder and Workspace Admin may ask; the stream is well formed (or 503 when the embedding model is off)", async () => {
  for (const [label, session] of [
    ["knowledge editor", thao],
    ["builder", minh],
    ["workspace admin", linh],
  ] as const) {
    const r = await ask(
      session,
      ws,
      restricted.id,
      askBody(Q.marryEn, { kind: "authenticated", groups: ["managers"] }),
    );
    if (embeddingUp) {
      const s = expectStream(r, { label });
      expect(s.passages.passages, `${label}: an empty collection has no passages`).toEqual([]);
      expect(s.done, label).toEqual({ outcome: "not_found", answer: "", citations: [] });
      expect(s.deltas, `${label}: no model text`).toEqual([]);
    } else {
      expectJsonError(r, 503, "model_unavailable", label);
    }
  }
});

test("AC1 TC-1-9: Viewer and Reviewer get 403 forbidden (no stream), whatever the principal", async () => {
  for (const [label, session] of [
    ["viewer", son],
    ["reviewer", ha],
  ] as const) {
    for (const col of [restricted.id, authenticated.id, publicCol.id]) {
      for (const principal of [AUTH, { kind: "anonymous", groups: [] }]) {
        const r = await ask(session, ws, col, askBody(Q.marryEn, principal));
        expectJsonError(r, 403, "forbidden", `${label} ${col}`);
      }
    }
  }
});

test("AC4 TC-4-3: the passages frame names the language of the question (vi for diacritics, NFD too; en otherwise); an empty collection ends in not_found", async () => {
  test.skip(!embeddingUp, "needs the embedding service (profile model)");
  const cases: [string, "vi" | "en"][] = [
    [Q.marryVi, "vi"],
    [Q.marryVi.normalize("NFD"), "vi"],
    [Q.annualVi, "vi"],
    [Q.marryEn, "en"],
    ["12345", "en"],
    ["How many ngày nghỉ phép?", "vi"],
  ];
  for (const [question, language] of cases) {
    const s = expectStream(await ask(thao, ws, authenticated.id, askBody(question)), {
      label: question,
    });
    expect(s.passages.language, question).toBe(language);
    expect(s.done?.outcome).toBe("not_found");
  }
  // Vietnamese without diacritics: the contract says "else en" (record what the box does).
  const plain = expectStream(
    await ask(thao, ws, authenticated.id, askBody("Ket hon duoc nghi may ngay?")),
  );
  expect(
    plain.passages.language,
    "no Vietnamese letters or diacritics -> en (contract wording)",
  ).toBe("en");
});

test("AC6 TC-6-4: an Anonymous principal with groups, an unknown kind or a non-list groups value is 422 invalid_request", async () => {
  const bad: [string, unknown][] = [
    ["anonymous with groups", { kind: "anonymous", groups: ["managers"] }],
    ["unknown kind", { kind: "admin", groups: [] }],
    ["kind with other case", { kind: "Authenticated", groups: [] }],
    ["empty kind", { kind: "", groups: [] }],
    ["null kind", { kind: null, groups: [] }],
    ["numeric kind", { kind: 5, groups: [] }],
    ["groups as a string", { kind: "authenticated", groups: "managers" }],
    ["groups with a number", { kind: "authenticated", groups: [1] }],
    ["groups with null", { kind: "authenticated", groups: [null] }],
    ["principal as a string", "authenticated"],
    ["principal as null", null],
  ];
  for (const [label, principal] of bad) {
    expectJsonError(
      await ask(thao, ws, restricted.id, askBody(Q.marryEn, principal)),
      422,
      "invalid_request",
      label,
    );
  }
  // principal is required: there is no default person.
  expectJsonError(
    await ask(thao, ws, restricted.id, { question: Q.marryEn }),
    422,
    "invalid_request",
    "principal missing",
  );
  expectJsonError(
    await ask(thao, ws, restricted.id, { question: Q.marryEn, principal: {} }),
    422,
    "invalid_request",
    "principal without kind",
  );
});

test("AC6 TC-6-6: groups are optional; up to 100 distinct names are accepted (case-insensitive), 101 or more are 422 invalid_group; bad names are invalid_group", async () => {
  const outcome = (r: Awaited<ReturnType<typeof ask>>, label: string): void => {
    if (embeddingUp) expectStream(r, { label });
    else expectJsonError(r, 503, "model_unavailable", label);
  };
  const names = (n: number, prefix = "group"): string[] =>
    Array.from({ length: n }, (_, i) => `${prefix}${i + 1}`);
  // groups absent: valid for both kinds (default []).
  outcome(
    await ask(thao, ws, restricted.id, {
      question: Q.marryEn,
      principal: { kind: "authenticated" },
    }),
    "authenticated without groups key",
  );
  outcome(
    await ask(thao, ws, restricted.id, { question: Q.marryEn, principal: { kind: "anonymous" } }),
    "anonymous without groups key",
  );
  // The collection form's limit of 20 does not apply: 21 and 100 distinct names are accepted.
  for (const count of [21, 100]) {
    outcome(
      await ask(
        thao,
        ws,
        restricted.id,
        askBody(Q.marryEn, { kind: "authenticated", groups: names(count) }),
      ),
      `${count} groups`,
    );
  }
  // Duplicates are normalised: 100 entries that are only 50 distinct names are accepted.
  const dupes = [...names(50), ...names(50).map((n) => n.toUpperCase())];
  outcome(
    await ask(
      thao,
      ws,
      restricted.id,
      askBody(Q.marryEn, { kind: "authenticated", groups: dupes }),
    ),
    "100 entries / 50 distinct groups",
  );
  // More than 100 items is refused before normalising, even when they dedupe to 60 names.
  expectJsonError(
    await ask(
      thao,
      ws,
      restricted.id,
      askBody(Q.marryEn, {
        kind: "authenticated",
        groups: [...names(60), ...names(60).map((n) => n.toUpperCase()), ...names(30)],
      }),
    ),
    422,
    "invalid_group",
    "150 entries / 60 distinct groups",
  );
  // 101 and more distinct names, and bad names, are invalid_group.
  for (const [label, groups] of [
    ["101 distinct names", names(101)],
    ["300 distinct names", names(300)],
    ["empty name", ["managers", ""]],
    ["blank name", ["managers", "   "]],
    ["control character", ["man\u0007agers"]],
    ["newline in a name", ["man\nagers"]],
    ["comma", ["a,b"]],
    ["65 characters", ["x".repeat(65)]],
  ] as [string, string[]][]) {
    expectJsonError(
      await ask(thao, ws, restricted.id, askBody(Q.marryEn, { kind: "authenticated", groups })),
      422,
      "invalid_group",
      label,
    );
  }
  // 64 characters is fine.
  outcome(
    await ask(
      thao,
      ws,
      restricted.id,
      askBody(Q.marryEn, { kind: "authenticated", groups: ["x".repeat(64)] }),
    ),
    "64-character group",
  );
});

test("Attack TC-A-13: order of checks: CSRF, session, permission, body, collection, models", async () => {
  const bad = askBody("");
  const valid = askBody(Q.marryEn);
  // Viewer + bad body -> 403 (permission before body).
  expectJsonError(await ask(son, ws, restricted.id, bad), 403, "forbidden", "viewer + bad body");
  // Unknown collection + bad body -> 422 (body before collection).
  expectJsonError(
    await ask(thao, ws, randomUUID(), bad),
    422,
    "invalid_request",
    "unknown collection + bad body",
  );
  // Unknown collection + valid body -> 404.
  expectJsonError(await ask(thao, ws, randomUUID(), valid), 404, "not_found", "unknown collection");
  // No session + bad body -> 401; no CSRF + bad body -> 403.
  const csrf = thao.csrfCookie as string;
  expectJsonError(
    await ask(thao, ws, restricted.id, bad, { cookies: { ei_csrf: csrf } }),
    401,
    "unauthenticated",
    "no session + bad body",
  );
  const noCsrf = await ask(thao, ws, restricted.id, bad, { csrf: "none" });
  expect(noCsrf.status, noCsrf.text).toBe(403);
  // invalid_group on an unknown collection -> 422 as well.
  expectJsonError(
    await ask(
      thao,
      ws,
      randomUUID(),
      askBody(Q.marryEn, { kind: "authenticated", groups: ["a,b"] }),
    ),
    422,
    "invalid_group",
    "unknown collection + bad group",
  );
});

test("Attack TC-A-3: fields that carry identity (org_id, user_id, workspace_id, principal.user_id ...) or anything unknown are 422 invalid_request", async () => {
  const uuid = randomUUID();
  const extras: [string, unknown][] = [
    ["org_id", { ...(askBody(Q.marryEn) as object), org_id: uuid }],
    ["user_id", { ...(askBody(Q.marryEn) as object), user_id: uuid }],
    ["workspace_id", { ...(askBody(Q.marryEn) as object), workspace_id: ws }],
    ["collection_id", { ...(askBody(Q.marryEn) as object), collection_id: uuid }],
    ["model", { ...(askBody(Q.marryEn) as object), model: "other" }],
    ["strict", { ...(askBody(Q.marryEn) as object), strict: false }],
    ["top_k", { ...(askBody(Q.marryEn) as object), top_k: 50 }],
    ["principal.user_id", askBody(Q.marryEn, { ...AUTH, user_id: uuid })],
    ["principal.org_id", askBody(Q.marryEn, { ...AUTH, org_id: uuid })],
    ["principal.email", askBody(Q.marryEn, { ...AUTH, email: "x@example.com" })],
  ];
  for (const [label, body] of extras) {
    expectJsonError(await ask(thao, ws, restricted.id, body), 422, "invalid_request", label);
  }
});

test("Attack TC-A-8: the question must be 1-2000 characters after trimming (empty, blank, 2001, wrong types, broken JSON are 422 invalid_request); 2000 passes", async () => {
  const bad: [string, unknown][] = [
    ["empty", askBody("")],
    ["spaces", askBody("     ")],
    ["tabs and newlines", askBody("\n\t \r\n")],
    ["2001 ASCII characters", askBody("a".repeat(2001))],
    ["2001 Vietnamese characters", askBody("ệ".repeat(2001))],
    ["2001 characters after trimming", askBody(` ${"a".repeat(2001)} `)],
    ["null", askBody(null)],
    ["number", askBody(42)],
    ["list", askBody(["x"])],
    ["object", askBody({ text: "x" })],
    ["missing", { principal: AUTH }],
    ["empty object", {}],
    ["a list instead of an object", [askBody("x")]],
    [
      "too many groups",
      askBody("x", {
        kind: "authenticated",
        groups: Array.from({ length: 101 }, (_, i) => `group${i + 1}`),
      }),
    ],
  ];
  for (const [label, body] of bad) {
    const r = await ask(thao, ws, restricted.id, body);
    if (label === "too many groups") {
      expectJsonError(r, 422, "invalid_group", label);
      continue;
    }
    expectJsonError(r, 422, "invalid_request", label);
  }
  expectJsonError(
    await ask(thao, ws, restricted.id, null, { rawBody: "{not json" }),
    422,
    "invalid_request",
    "broken JSON",
  );
  expectJsonError(
    await ask(thao, ws, restricted.id, null, { rawBody: "" }),
    422,
    "invalid_request",
    "empty body",
  );
  // The limits themselves are valid: 2000 characters, and 2000 + surrounding blanks (trimmed first).
  const valid = [
    "a".repeat(2000),
    "ệ".repeat(2000),
    `${"a".repeat(1990)}${" ".repeat(20)}`,
    `  ${"a".repeat(2000)}  `,
    "?",
  ];
  for (const question of valid) {
    const r = await ask(
      thao,
      ws,
      restricted.id,
      askBody(question, { kind: "authenticated", groups: ["managers"] }),
    );
    if (embeddingUp) expectStream(r, { label: `${question.length} characters` });
    else expectJsonError(r, 503, "model_unavailable", `${question.length} characters`);
  }
});

test("AC6 TC-6-5: group names the collection form would reject are 422 invalid_group", async () => {
  const bad: [string, string[]][] = [
    ["65 characters", ["a".repeat(65)]],
    ["a comma inside a name", ["managers", "a,b"]],
  ];
  for (const [label, groups] of bad) {
    expectJsonError(
      await ask(thao, ws, restricted.id, askBody(Q.marryEn, { kind: "authenticated", groups })),
      422,
      "invalid_group",
      label,
    );
  }
});

test("Attack TC-A-5: no session, an invalid session and a revoked-looking session are 401 unauthenticated with no stream", async () => {
  const csrf = thao.csrfCookie as string;
  expect(csrf, "precondition: the session has a CSRF cookie").toBeTruthy();
  for (const [label, cookies] of [
    ["no session", { ei_csrf: csrf }],
    ["invalid session", { ei_csrf: csrf, ei_session: `${randomUUID()}.${"x".repeat(43)}` }],
    ["garbage session", { ei_csrf: csrf, ei_session: "garbage" }],
  ] as const) {
    expectJsonError(
      await ask(thao, ws, restricted.id, askBody(Q.marryEn), { cookies }),
      401,
      "unauthenticated",
      label,
    );
  }
});

test("Attack TC-A-7: a missing or wrong CSRF token is 403 (existing CSRF answer) and nothing streams", async () => {
  for (const csrf of ["none", "not-the-token"]) {
    const r = await ask(thao, ws, restricted.id, askBody(Q.marryEn), { csrf });
    expect(r.status, `csrf=${csrf}: ${r.text}`).toBe(403);
    expect(r.contentType).not.toMatch(/event-stream/);
    expect(r.frames).toEqual([]);
  }
});

test("Attack TC-A-1: a Sông Hàn Retail collection, a collection of another Workspace, a deleted collection and a random id all give the same 404 not_found", async () => {
  const valid = askBody(Q.marryEn);
  const random = await ask(thao, ws, randomUUID(), valid);
  expectJsonError(random, 404, "not_found", "random uuid");
  const sameAsRandom = (label: string, r: Awaited<ReturnType<typeof ask>>): void => {
    expect(r.status, label).toBe(404);
    expect(r.text, `${label}: byte-identical body`).toBe(random.text);
    expect(headerNamesOf(r), `${label}: same header names`).toEqual(headerNamesOf(random));
    expect(r.contentType, `${label}: same content type`).toBe(random.contentType);
  };
  sameAsRandom("Sông Hàn collection in a People Ops path", await ask(thao, ws, songhan.id, valid));
  sameAsRandom(
    "Engineering collection in a People Ops path",
    await ask(thao, ws, engineering.id, valid),
  );
  sameAsRandom(
    "Sông Hàn collection, as the Org Admin of Mekong",
    await ask(linh, ws, songhan.id, valid),
  );
  // A deleted collection.
  const doomed = await makeCollection(linh, ws, "Bare Doomed", "public");
  const removed = await linh.send("DELETE", `/api/workspaces/${ws}/collections/${doomed.id}`);
  expect([200, 204], removed.text).toContain(removed.status);
  sameAsRandom("deleted collection", await ask(thao, ws, doomed.id, valid));
  // The other direction: Sông Hàn's user with a Mekong collection id in the Sông Hàn Workspace path.
  const reverse = await ask(ngan, shWs, restricted.id, valid);
  expectJsonError(reverse, 404, "not_found", "Mekong collection from Sông Hàn");
  expect(reverse.text).toBe(random.text);
  // Another Workspace's path with the user's role missing there: the status is recorded (contract is silent).
  const otherWs = await ask(thao, engWs, engineering.id, valid);
  note(
    `Knowledge Editor of People Ops asking in the Engineering Workspace path: ${otherWs.status} ${otherWs.text}`,
  );
  expect([401, 403, 404], "never a stream for a Workspace where the user has no role").toContain(
    otherWs.status,
  );
  expect(otherWs.frames).toEqual([]);
});

test("Attack TC-A-12: none of the rejected requests (401, 403, 404, 422) reaches the model: no answer_done line, no new rows", async () => {
  const before = answerDoneLines().length;
  const rowsBefore = counts37();
  const valid = askBody(Q.marryEn);
  await ask(thao, ws, randomUUID(), valid);
  await ask(thao, ws, songhan.id, valid);
  await ask(thao, ws, engineering.id, valid);
  await ask(son, ws, restricted.id, valid);
  await ask(ha, ws, restricted.id, valid);
  await ask(thao, ws, restricted.id, valid, { csrf: "none" });
  await ask(thao, ws, restricted.id, valid, { cookies: { ei_csrf: thao.csrfCookie as string } });
  await ask(thao, ws, restricted.id, askBody("")); // 422
  await ask(thao, ws, restricted.id, { ...(valid as object), org_id: randomUUID() }); // 422
  expect(answerDoneLines().length, "no answer_done line for rejected requests").toBe(before);
  expect(counts37(), "no rows written").toEqual(rowsBefore);
});

test("AC1 TC-1-10: odd but valid questions (emoji, right-to-left text, quotes, SQL, HTML, a NUL character) never end in a 5xx", async () => {
  const odd = [
    "🙂 Kết hôn được nghỉ mấy ngày? 🎉",
    "مرحبا كم يوم إجازة؟",
    `'; drop table collections; -- "quoted" \\ % _`,
    "<script>alert(1)</script> {{7*7}} ${jndi:ldap://x}",
    "line one\nline two\r\nline three\ttab",
    "bad\u0000byte",
    "é combining and NFD: Kết hôn",
  ];
  for (const question of odd) {
    const r = await ask(thao, ws, authenticated.id, askBody(question));
    expect([200, 422, 503], `${JSON.stringify(question)}: ${r.text.slice(0, 200)}`).toContain(
      r.status,
    );
    if (r.status === 200) expectStream(r, { label: question });
    if (r.status !== 200) expect(r.json).toHaveProperty("detail");
    if (embeddingUp)
      expect(r.status, `${JSON.stringify(question)} is a normal question`).not.toBe(503);
  }
});

test("AC1 TC-1-11: five asks at once on one session all end the same way (no shared state between asks)", async () => {
  const results = await Promise.all(
    Array.from({ length: 5 }, (_, i) =>
      ask(thao, ws, publicCol.id, askBody(i % 2 === 0 ? Q.marryVi : Q.marryEn)),
    ),
  );
  results.forEach((r, i) => {
    if (embeddingUp) {
      const s = expectStream(r, { label: `parallel ${i}` });
      expect(s.passages.language).toBe(i % 2 === 0 ? "vi" : "en");
      expect(s.done?.outcome).toBe("not_found");
    } else {
      expectJsonError(r, 503, "model_unavailable", `parallel ${i}`);
    }
  });
});

test("AC7 TC-7-5: with the embedding model off the route answers 503 model_unavailable (JSON, nothing else); with it on the same call streams", async () => {
  const r = await ask(thao, ws, authenticated.id, askBody(Q.marryEn));
  if (embeddingUp) {
    expectStream(r, { label: "embedding up" });
    note("embedding service is up: the 503 branch is covered by AC7 TC-7-3 (slow)");
  } else {
    expectJsonError(r, 503, "model_unavailable", "embedding down");
  }
});

test("AC5 TC-5-6: the stream headers: Content-Type, Cache-Control no-store through the admin origin, X-Accel-Buffering no on the API port (nginx consumes it)", async () => {
  const body = askBody(Q.marryEn);
  const viaAdmin = await ask(thao, ws, restricted.id, body);
  if (embeddingUp) {
    expectStream(viaAdmin, { label: "admin origin" });
    expect(viaAdmin.headers["cache-control"]).toBe("no-store");
  } else {
    expectJsonError(viaAdmin, 503, "model_unavailable", "admin origin");
  }
  const direct = await ask(thao, ws, restricted.id, body, {
    apiBase: "http://127.0.0.1:8000",
  }).catch(() => null);
  test.skip(!direct || direct.status === 0, "the API port 8000 is not reachable from the host");
  if (embeddingUp) {
    expect(direct?.status).toBe(200);
    expect(direct?.contentType).toMatch(/^text\/event-stream/);
    expect(direct?.headers["cache-control"]).toBe("no-store");
    expect(direct?.headers["x-accel-buffering"], "X-Accel-Buffering on the API port").toBe("no");
  }
});
