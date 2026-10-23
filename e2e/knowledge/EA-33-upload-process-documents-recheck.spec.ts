// EA-33 (KB-02) round 2 recheck of the round 1 bugs, driven through the real UI (slow network, API restart).
// Runs against a running, migrated and seeded stack:
//   npm run e2e -- e2e/knowledge/EA-33-upload-process-documents-recheck.spec.ts
// Q1-1 CSRF race on parallel uploads after a fresh load, Q1-4 stale "was not uploaded" line cleared on
// re-upload, Q1-3 visual rules of the CollectionDetail artboard, Q1-2 list recovery after
// `docker compose restart api`. Data: own folders/documents with the marker `qa-EA33-<run>`; removed in
// afterAll (counts proven equal).
import fs from "node:fs";
import { expect, test } from "@playwright/test";
import { compose, peopleOpsId, type ApiSession } from "../support/ea22";
import { withSession } from "../support/ea23";
import { collectionsPath, json, type CollectionItem } from "../support/ea32";
import {
  MARK,
  SCREENSHOTS_33,
  apiOf,
  buildScannedPdf,
  chooseFiles,
  cleanupAll,
  counts,
  docRow,
  expectStatusText,
  filler,
  makeFolder,
  markerRows,
  mustReady,
  mustUpload,
  openCollectionPage,
  randomJunk,
  ready,
  rejectionLines,
  selectFolder,
  tempFile,
  waitStatus,
  type Counts,
} from "../support/ea33";

test.describe.configure({ mode: "serial", timeout: 300_000 });

let ws = "";
let col = "";
let baseline: Counts | undefined;
let linh: ApiSession;
let thao: ApiSession;

test.beforeAll(async () => {
  await cleanupAll();
  fs.mkdirSync(SCREENSHOTS_33, { recursive: true });
  baseline = counts();
  ws = peopleOpsId();
  linh = await apiOf("linh");
  thao = await apiOf("thao");
  const result = await linh.send("GET", collectionsPath(ws));
  const handbook = json<{ collections: CollectionItem[] }>(result).collections.find(
    (entry) => entry.name === "Employee Handbook",
  );
  col = (handbook as CollectionItem).id;
});

test.afterAll(async () => {
  await cleanupAll();
  if (baseline) expect(counts(), "rows left behind").toEqual(baseline);
  expect(markerRows(), "rows with the marker left behind").toEqual([]);
});

test("Q1-1 recheck: 8 fresh page loads on a slow network, 5 files each: every POST is 201 and no rejection line", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "r2-csrf");
  const statuses: number[] = [];
  const csrfGets: number[] = [];
  let total = 0;
  for (let attempt = 0; attempt < 8; attempt++) {
    const paths = Array.from({ length: 5 }, (_, index) =>
      tempFile(`${MARK}-r2-${attempt}-${index}.txt`, filler(`zqr2${attempt}`, 400)),
    );
    await withSession(browser, thao, async (page) => {
      const cdp = await page.context().newCDPSession(page);
      await cdp.send("Network.enable");
      await cdp.send("Network.emulateNetworkConditions", {
        offline: false,
        latency: attempt % 2 === 0 ? 120 : 20,
        downloadThroughput: -1,
        uploadThroughput: -1,
      });
      let csrf = 0;
      page.on("request", (request) => {
        if (request.url().includes("/api/auth/csrf")) csrf += 1;
      });
      page.on("response", (response) => {
        if (response.request().method() === "POST" && /\/documents$/.test(response.url())) {
          statuses.push(response.status());
        }
      });
      await openCollectionPage(page, ws, col);
      await selectFolder(page, folder.name);
      await chooseFiles(page, paths);
      total += 5;
      await expect(page.getByTestId("document-row")).toHaveCount(total, { timeout: 30_000 });
      expect(await rejectionLines(page)).toEqual([]);
      csrfGets.push(csrf);
    });
  }
  expect(statuses.length).toBe(40);
  expect(
    statuses.every((status) => status === 201),
    statuses.join(","),
  ).toBe(true);
  test.info().annotations.push({ type: "csrf-gets-per-load", description: csrfGets.join(",") });
});

test("Q1-4 recheck: a failed upload line disappears when the same file is uploaded again", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "r2-stale");
  const path = tempFile(`${MARK}-r2-stale.txt`, filler("zqstale", 400));
  await withSession(browser, thao, async (page) => {
    let blocked = true;
    await page.route(/\/documents$/, async (route) => {
      if (route.request().method() === "POST" && blocked) {
        blocked = false;
        await route.fulfill({
          status: 403,
          contentType: "application/json",
          body: '{"detail":"csrf"}',
        });
      } else {
        await route.continue();
      }
    });
    await openCollectionPage(page, ws, col);
    await selectFolder(page, folder.name);
    await chooseFiles(page, [path]);
    await expect(page.getByTestId("upload-rejection")).toHaveCount(1);
    expect((await rejectionLines(page))[0]).toContain("was not uploaded");
    await page.screenshot({ path: `${SCREENSHOTS_33}/r2-q14-stale-before.png` });
    await chooseFiles(page, [path]);
    await expect(docRow(page, `${MARK}-r2-stale.txt`)).toHaveCount(1);
    await expect(page.getByTestId("upload-rejection")).toHaveCount(0);
    await page.screenshot({ path: `${SCREENSHOTS_33}/r2-q14-stale-after.png` });
  });
});

test("Q1-3 recheck: visual rules of the CollectionDetail artboard (status colours, tinted rows, text links, one-line drop zone, readable cells)", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "r2-visual");
  const at = { ws, col, folder: folder.id };
  await mustReady(thao, at, `${MARK}-r2-ok.txt`, Buffer.from(filler("zqv", 500)));
  const scan = await mustUpload(thao, at, `${MARK}-r2-scan.pdf`, buildScannedPdf(2));
  const bad = await mustUpload(thao, at, `${MARK}-r2-bad.pdf`, randomJunk(4096));
  await waitStatus(thao, ws, col, scan.id);
  await waitStatus(thao, ws, col, bad.id);
  await withSession(browser, thao, async (page) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openCollectionPage(page, ws, col);
    await selectFolder(page, folder.name);
    await expect(page.getByTestId("document-row")).toHaveCount(3);
    await page.screenshot({ path: `${SCREENSHOTS_33}/r2-q13-detail.png`, fullPage: true });
    const okName = `${MARK}-r2-ok.txt`;
    const notes: string[] = [];
    const bodyColor = await page.evaluate(() => getComputedStyle(document.body).color);
    const readyColor = await docRow(page, okName)
      .getByTestId("document-status")
      .evaluate((el) => getComputedStyle(el).color);
    notes.push(`body ${bodyColor}`, `ready ${readyColor}`);
    expect(readyColor, "Ready is green").not.toBe(bodyColor);
    const rowBg = (name: string): Promise<string> =>
      docRow(page, name).evaluate((el) => {
        const own = getComputedStyle(el).backgroundColor;
        const cell = getComputedStyle(el.querySelector("td") as Element).backgroundColor;
        return `${own}|${cell}`;
      });
    const bgs = {
      ok: await rowBg(okName),
      scan: await rowBg(`${MARK}-r2-scan.pdf`),
      bad: await rowBg(`${MARK}-r2-bad.pdf`),
    };
    notes.push(JSON.stringify(bgs));
    expect(bgs.scan, "Not supported row is tinted").not.toBe(bgs.ok);
    expect(bgs.bad, "Failed row is tinted").not.toBe(bgs.ok);
    const remove = docRow(page, `${MARK}-r2-bad.pdf`).getByTestId("remove-document");
    expect(await remove.evaluate((el) => getComputedStyle(el).borderTopWidth)).toBe("0px");
    const preview = docRow(page, okName).getByTestId("preview-text");
    expect(await preview.evaluate((el) => getComputedStyle(el).borderTopWidth)).toBe("0px");
    notes.push(
      `preview-text height ${(await preview.boundingBox())?.height} (Q2-2: wraps on two lines when above 28)`,
    );
    const rowBox = await docRow(page, okName).boundingBox();
    notes.push(`row height ${rowBox?.height}`);
    expect(rowBox?.height).toBeLessThan(80);
    const zone = await page.getByTestId("drop-zone").boundingBox();
    notes.push(`drop zone height ${zone?.height}`);
    expect(zone?.height, "one-line banner").toBeLessThan(110);
    const updated = await docRow(page, okName).getByTestId("document-updated").boundingBox();
    expect.soft(updated?.height, "Updated cell on at most two lines").toBeLessThan(80);
    await page.screenshot({ path: `${SCREENSHOTS_33}/r2-q13-detail.png`, fullPage: true });
    test.info().annotations.push({ type: "styles", description: notes.join(" ; ") });
  });
});

test("Q1-2 recheck: the list keeps refreshing and recovers after the API restarts with uploads just finished", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "r2-restart");
  const big = [0, 1].map((index) =>
    tempFile(`${MARK}-r2-big-${index}.txt`, `${filler(`zqbig${index}`, 1000)} `.repeat(30_000)),
  );
  const small = tempFile(`${MARK}-r2-small.txt`, filler("zqsm", 400));
  await withSession(browser, thao, async (page) => {
    await openCollectionPage(page, ws, col);
    await selectFolder(page, folder.name);
    await chooseFiles(page, [small, ...big]);
    await expect(page.getByTestId("document-row")).toHaveCount(3, { timeout: 60_000 });
    compose(["restart", "api"]);
    await expect(page.getByText("Something went wrong")).toHaveCount(0, { timeout: 120_000 });
    await expect(page.getByTestId("document-row")).toHaveCount(3, { timeout: 120_000 });
    await expectStatusText(docRow(page, `${MARK}-r2-small.txt`), /^(Ready|Failed)/, 150_000);
    await expect(page.getByText("Something went wrong")).toHaveCount(0);
    await page.screenshot({ path: `${SCREENSHOTS_33}/r2-q12-after-restart.png`, fullPage: true });
  });
  expect(ready(1)).toBeTruthy();
});
