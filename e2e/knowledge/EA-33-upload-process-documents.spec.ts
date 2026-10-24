// EA-33 (KB-02): upload and process PDF/DOCX/MD/TXT documents into normalised chunks.
// Black-box specs written from .work/EA-33/contract.md and ticket.md only. Runs against a running,
// migrated and seeded stack:
//   npm run up -- --no-model && npm run seed && npm run e2e -- e2e/knowledge/EA-33-upload-process-documents.spec.ts
// Data: seeded accounts (Linh Tran admin, Thao Nguyen knowledge editor); every folder, collection and file
// is named with the marker `qa-EA33-<run>` and lives in "Employee Handbook" (own folders) or in own
// collections. Seed rows are never changed. cleanupAll() removes everything (documents first, then
// folders, collections, audit rows); afterAll proves the row counts equal the counts before the run.
// Other files of the ticket: ...-access.spec.ts (AC8 and the attack list), ...-limits.spec.ts (AC3, @slow,
// and the 50 MB / quota cases), ...-perf.spec.ts (NFR, @perf).
import fs from "node:fs";
import { expect, test } from "@playwright/test";
import { DEMO_ORG, peopleOpsId, sleep, sql, watch, type ApiSession } from "../support/ea22";
import { withSession } from "../support/ea23";
import {
  collectionsPath,
  json,
  withoutStatuses,
  rowOf,
  type CollectionItem,
} from "../support/ea32";
import {
  ACCOUNT,
  DOCUMENT_KEYS,
  MARK,
  MSG,
  OVERTIME,
  OVERTIME_VI,
  SCREENSHOTS_33,
  apiOf,
  auditOf,
  auditRowsContaining,
  buildDocx,
  buildEmptyDocx,
  buildMd,
  buildPasswordPdf,
  buildPdf,
  buildScannedPdf,
  buildZipBombDocx,
  chooseFiles,
  chunkRows,
  chunksOf,
  chunksPath,
  cleanupAll,
  counts,
  deleteDoc,
  docRow,
  exactText,
  expectChunkInvariants,
  expectSectionsRespected,
  expectStatusText,
  filler,
  fillerVi,
  folderCount,
  folderRowOf,
  formatSize,
  getDoc,
  listDocs,
  makeCollection,
  makeFolder,
  markerRows,
  markersIn,
  mustReady,
  mustUpload,
  openCollectionPage,
  randomJunk,
  ready,
  rejectionLines,
  selectAllDocuments,
  selectFolder,
  storedFiles,
  tempFile,
  textOf,
  textPath,
  uploadRaw,
  uploadRequests,
  waitStatus,
  waitStoredGone,
  type Chunk,
  type Counts,
  type DocumentItem,
  type FolderItem33,
  type Loc,
} from "../support/ea33";

test.describe.configure({ mode: "serial", timeout: 240_000 });

let ws = "";
let col = "";
let baseline: Counts | undefined;
let linh: ApiSession;
let thao: ApiSession;

function loc(folder: FolderItem33): Loc {
  return { ws, col, folder: folder.id };
}

function userIdOf(email: string): string {
  return sql(`select id from users where org_id = '${DEMO_ORG}' and email = '${email}'`);
}

async function handbookTotal(): Promise<number> {
  const result = await linh.send("GET", collectionsPath(ws));
  expect(result.status, result.text).toBe(200);
  const item = json<{ collections: CollectionItem[] }>(result).collections.find(
    (entry) => entry.id === col,
  );
  return item?.documents.total ?? -1;
}

test.beforeAll(async () => {
  await cleanupAll();
  fs.mkdirSync(SCREENSHOTS_33, { recursive: true });
  baseline = counts();
  ws = peopleOpsId();
  linh = await apiOf("linh");
  thao = await apiOf("thao");
  const result = await linh.send("GET", collectionsPath(ws));
  expect(result.status, result.text).toBe(200);
  const handbook = json<{ collections: CollectionItem[] }>(result).collections.find(
    (entry) => entry.name === "Employee Handbook",
  );
  expect(handbook, "precondition: the demo seed created Employee Handbook").toBeTruthy();
  col = (handbook as CollectionItem).id;
});

test.afterAll(async () => {
  await cleanupAll();
  if (baseline) expect(counts(), "rows left behind").toEqual(baseline);
  expect(markerRows(), "rows with the EA-33 marker left behind").toEqual([]);
});

// ---------------------------------------------------------------------------------------------
// AC1 Upload
// ---------------------------------------------------------------------------------------------

test("AC1: five supported files chosen with Browse each show their status and become Ready · N pages without a reload", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "ac1-main");
  const files = [
    {
      name: `${MARK}-ac1-three-pages.pdf`,
      bytes: buildPdf([filler("zqpg1", 700), filler("zqpg2", 700), filler("zqpg3", 700)]),
      status: ready(3),
    },
    {
      name: `${MARK}-ac1-policy.docx`,
      bytes: buildDocx(OVERTIME, { pages: 4 }),
      status: ready(4),
    },
    {
      name: `${MARK}-ac1-policy.md`,
      bytes: Buffer.from(buildMd(OVERTIME)),
      status: /^Ready · \d+ pages?$/,
    },
    { name: `${MARK}-ac1-notes.txt`, bytes: Buffer.from(filler("zqtxt", 2500)), status: ready(1) },
    {
      name: `${MARK}-ac1-one-page.pdf`,
      bytes: buildPdf([filler("zqpg1", 600)]),
      status: ready(1),
    },
  ];
  const paths = files.map((file) => tempFile(file.name, file.bytes));
  const totalBefore = await handbookTotal();

  await withSession(browser, thao, async (page) => {
    const seen = watch(page);
    await openCollectionPage(page, ws, col);
    await selectFolder(page, folder.name);
    await expect(folderCount(page, folder.name)).toHaveText("0");
    await page.evaluate(() => {
      (window as unknown as { __qaLoaded: boolean }).__qaLoaded = true;
    });

    await chooseFiles(page, paths);
    await expect(page.getByTestId("document-row")).toHaveCount(5);
    for (const row of await page.getByTestId("document-row").all()) {
      expect(["queued", "processing", "ready"]).toContain(await row.getAttribute("data-status"));
      await expect(row.getByTestId("document-status")).not.toHaveText("");
    }

    for (const file of files) {
      const row = docRow(page, file.name);
      await expect(row).toHaveCount(1);
      await expectStatusText(row, file.status);
      await expect(row).toHaveAttribute("data-status", "ready");
      await expect(row.getByTestId("document-size")).toHaveText(formatSize(file.bytes.length));
      await expect(row.getByTestId("document-updated")).toHaveText("Today · Thao Nguyen");
      await expect(row.getByTestId("document-reason")).toHaveCount(0);
      await expect(row.getByTestId("preview-text")).toHaveAccessibleName(
        `Preview text of ${file.name}`,
      );
      await expect(row.getByTestId("remove-document")).toHaveCount(0);
    }
    expect(
      await page.evaluate(() => (window as unknown as { __qaLoaded?: boolean }).__qaLoaded),
      "the page was not reloaded",
    ).toBe(true);
    await expect(folderCount(page, folder.name)).toHaveText("5");
    const allCount = page.getByTestId("all-documents").getByTestId("folder-count");
    await expect(allCount).toHaveText(String(totalBefore + 5));
    await page.screenshot({ path: `${SCREENSHOTS_33}/ac1-five-ready.png`, fullPage: true });

    // The Collections list shows the real total.
    await page.goto(`/w/${ws}/knowledge`);
    await expect(page.getByTestId("knowledge-page")).toBeVisible();
    const listRow = rowOf(page, "Employee Handbook");
    await expect(listRow.getByTestId("document-count")).toHaveText(String(totalBefore + 5));
    await expect(listRow.getByTestId("collection-status")).not.toHaveText("No documents");
    expect(withoutStatuses(seen.problems, [])).toEqual([]);
  });

  const listed = await listDocs(thao, ws, col, folder.id);
  expect(listed).toHaveLength(5);
  for (const item of listed) {
    expect(item.status, item.name).toBe("ready");
    expect(item.page_count, item.name).toBeGreaterThanOrEqual(1);
  }
  expect(listed.find((item) => item.name.endsWith("three-pages.pdf"))?.page_count).toBe(3);
  expect(listed.find((item) => item.name.endsWith("one-page.pdf"))?.page_count).toBe(1);
  expect(listed.find((item) => item.name.endsWith("policy.docx"))?.page_count).toBe(4);
});

test("AC1 TC-1-2: the upload API answers 201 with a queued DocumentItem; the list is newest first, filtered by folder and carries the uploader", async () => {
  const folderA = await makeFolder(linh, ws, col, "ac1-api-a");
  const folderB = await makeFolder(linh, ws, col, "ac1-api-b");
  const names = ["first", "second", "third"].map((word) => `${MARK}-ac1-${word}.txt`);
  const created: DocumentItem[] = [];
  for (const name of names) {
    const result = await uploadRaw(thao, loc(folderA), name, Buffer.from(filler("zqapi", 400)));
    expect(result.status, result.text).toBe(201);
    const item = json<DocumentItem>(result);
    expect(Object.keys(item).sort()).toEqual(DOCUMENT_KEYS);
    expect(item).toMatchObject({
      folder_id: folderA.id,
      name,
      format: "txt",
      size_bytes: Buffer.byteLength(filler("zqapi", 400)),
      uploaded_by: { id: userIdOf(ACCOUNT.thao.email), display_name: "Thao Nguyen" },
    });
    expect(item.status).toBe("queued");
    expect(item.progress).toBeNull();
    expect(item.reason).toBeNull();
    expect(item.page_count).toBeNull();
    expect(Number.isNaN(Date.parse(item.created_at))).toBe(false);
    expect(Number.isNaN(Date.parse(item.updated_at))).toBe(false);
    created.push(item);
    await sleep(1100); // distinct created_at values
  }
  await mustReady(thao, loc(folderB), `${MARK}-ac1-other.txt`, Buffer.from(filler("zqother", 400)));
  for (const item of created) await waitStatus(thao, ws, col, item.id);

  const inA = await listDocs(thao, ws, col, folderA.id);
  expect(inA.map((item) => item.name)).toEqual([...names].reverse());
  for (const item of inA) {
    expect(item.status).toBe("ready");
    expect(item.progress).toBeNull();
    expect(item.reason).toBeNull();
    expect(item.page_count).toBe(1);
  }
  const inB = await listDocs(thao, ws, col, folderB.id);
  expect(inB.map((item) => item.name)).toEqual([`${MARK}-ac1-other.txt`]);
  const whole = await listDocs(thao, ws, col);
  for (const item of [...inA, ...inB]) {
    expect(whole.map((entry) => entry.id)).toContain(item.id);
  }
});

test("AC1 TC-1-3: file names with Vietnamese diacritics, spaces, & and a path part are stored as the base name and shown as uploaded", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "ac1-names");
  const vietnamese = `${MARK}-Bảng chấm công & phê duyệt (2026).txt`;
  const uploaded = await mustReady(
    thao,
    loc(folder),
    vietnamese,
    Buffer.from(fillerVi("zqvn", 500)),
  );
  expect(uploaded.name).toBe(vietnamese);
  const withPath = await uploadRaw(
    thao,
    loc(folder),
    `reports/2026/${MARK}-nested.txt`,
    Buffer.from(filler("zqpath", 300)),
  );
  expect(withPath.status, withPath.text).toBe(201);
  expect(json<DocumentItem>(withPath).name).toBe(`${MARK}-nested.txt`);
  await withSession(browser, thao, async (page) => {
    await openCollectionPage(page, ws, col);
    await selectFolder(page, folder.name);
    await expect(docRow(page, vietnamese).getByTestId("document-name")).toHaveText(vietnamese);
    await expect(docRow(page, `${MARK}-nested.txt`)).toHaveCount(1);
    await expect(docRow(page, vietnamese).getByTestId("preview-text")).toHaveAccessibleName(
      `Preview text of ${vietnamese}`,
    );
  });
});

test("AC1 TC-1-4: dropping files on the drop zone uploads them into the selected folder", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "ac1-drop");
  const name = `${MARK}-dropped.txt`;
  await withSession(browser, thao, async (page) => {
    await openCollectionPage(page, ws, col);
    await selectFolder(page, folder.name);
    const transfer = await page.evaluateHandle(
      ({ fileName, text }) => {
        const data = new DataTransfer();
        data.items.add(new File([text], fileName, { type: "text/plain" }));
        return data;
      },
      { fileName: name, text: filler("zqdrop", 500) },
    );
    const zone = page.getByTestId("drop-zone");
    await zone.dispatchEvent("dragenter", { dataTransfer: transfer });
    await zone.dispatchEvent("dragover", { dataTransfer: transfer });
    await zone.dispatchEvent("drop", { dataTransfer: transfer });
    const row = docRow(page, name);
    await expect(row).toHaveCount(1);
    await expectStatusText(row, ready(1));
  });
  const listed = await listDocs(thao, ws, col, folder.id);
  expect(listed.map((item) => item.name)).toEqual([name]);
});

test("AC1 TC-1-5: ten small files uploaded in parallel all reach Ready (fast)", async () => {
  const folder = await makeFolder(linh, ws, col, "ac1-parallel");
  const results = await Promise.all(
    Array.from({ length: 10 }, (_, index) =>
      uploadRaw(
        thao,
        loc(folder),
        `${MARK}-par-${index}.txt`,
        Buffer.from(filler(`zqpar${index}`, 800)),
      ),
    ),
  );
  const items = results.map((result) => {
    expect(result.status, result.text).toBe(201);
    return json<DocumentItem>(result);
  });
  expect(new Set(items.map((item) => item.id)).size).toBe(10);
  for (const item of items) {
    const done = await waitStatus(
      thao,
      ws,
      col,
      item.id,
      ["ready", "failed", "not_supported"],
      120_000,
    );
    expect(done.status, done.name).toBe("ready");
  }
  expect(await listDocs(thao, ws, col, folder.id)).toHaveLength(10);
  const folders = await linh.send("GET", `${collectionsPath(ws)}/${col}`);
  const detail = json<{ folders: FolderItem33[] }>(folders);
  expect(detail.folders.find((entry) => entry.id === folder.id)?.document_count).toBe(10);
});

test("AC1 TC-1-6: the Size column shows N B, N KB (1 KB = 1024 B) and N.N MB", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "ac1-size");
  const sizes = [500, 14_336, 1_258_291];
  const items = await Promise.all(
    sizes.map((size) =>
      mustUpload(thao, loc(folder), `${MARK}-size-${size}.txt`, Buffer.from(exactText(size))),
    ),
  );
  for (const item of items) await waitStatus(thao, ws, col, item.id);
  await withSession(browser, thao, async (page) => {
    await openCollectionPage(page, ws, col);
    await selectFolder(page, folder.name);
    await expect(docRow(page, `${MARK}-size-500.txt`).getByTestId("document-size")).toHaveText(
      "500 B",
    );
    await expect(docRow(page, `${MARK}-size-14336.txt`).getByTestId("document-size")).toHaveText(
      "14 KB",
    );
    await expect(docRow(page, `${MARK}-size-1258291.txt`).getByTestId("document-size")).toHaveText(
      "1.2 MB",
    );
  });
});

test("AC1 TC-1-7: N pages for DOCX (stored page count or an estimate) and for MD/TXT (one per 3 000 characters, at least 1)", async () => {
  const folder = await makeFolder(linh, ws, col, "ac1-pages");
  const cases: { name: string; bytes: Buffer; pages: number | "estimate" }[] = [
    { name: `${MARK}-pg-short.txt`, bytes: Buffer.from("A single short line of text."), pages: 1 },
    { name: `${MARK}-pg-6000.txt`, bytes: Buffer.from(exactText(6000)), pages: 2 },
    { name: `${MARK}-pg-6000.md`, bytes: Buffer.from(exactText(6000)), pages: 2 },
    { name: `${MARK}-pg-seven.docx`, bytes: buildDocx(OVERTIME, { pages: 7 }), pages: 7 },
    { name: `${MARK}-pg-nopages.docx`, bytes: buildDocx(OVERTIME), pages: "estimate" },
    {
      name: `${MARK}-pg-pdf.pdf`,
      bytes: buildPdf(Array.from({ length: 6 }, (_, index) => filler(`zqpg${index + 1}`, 500))),
      pages: 6,
    },
  ];
  for (const entry of cases) {
    const done = await mustReady(thao, loc(folder), entry.name, entry.bytes);
    if (entry.pages === "estimate") expect(done.page_count, entry.name).toBeGreaterThanOrEqual(1);
    else expect(done.page_count, entry.name).toBe(entry.pages);
  }
});

test("AC1 TC-1-8: a file waiting for its upload request shows Uploading… until the server accepts it", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "ac1-pending");
  const name = `${MARK}-slow-request.txt`;
  await withSession(browser, thao, async (page) => {
    await page.route(/\/folders\/[0-9a-f-]{36}\/documents$/, async (route) => {
      if (route.request().method() === "POST") await sleep(2000);
      await route.continue();
    });
    await openCollectionPage(page, ws, col);
    await selectFolder(page, folder.name);
    await chooseFiles(page, [tempFile(name, filler("zqslow", 400))]);
    const pending = page.getByTestId("upload-pending");
    await expect(pending.first()).toBeVisible();
    await expect(pending.first()).toContainText("Uploading…");
    await expect(page.getByTestId("upload-pending")).toHaveCount(0, { timeout: 15_000 });
    await expectStatusText(docRow(page, name), ready(1));
  });
});

test("AC1 TC-1-9: the list shows only the selected folder's documents, All documents lists the whole collection, counts and empty texts follow", async ({
  browser,
}) => {
  const own = await makeCollection(linh, ws, "scope");
  const folderA = await makeFolder(linh, ws, own.id, "scope-a");
  const sub = await makeFolder(linh, ws, own.id, "scope-child", folderA.id);
  const folderB = await makeFolder(linh, ws, own.id, "scope-b");
  const at = (folder: FolderItem33): Loc => ({ ws, col: own.id, folder: folder.id });
  const inA = await mustReady(
    thao,
    at(folderA),
    `${MARK}-scope-in-a.txt`,
    Buffer.from(filler("zqa", 300)),
  );
  const inSub = await mustReady(
    thao,
    at(sub),
    `${MARK}-scope-in-sub.txt`,
    Buffer.from(filler("zqs", 300)),
  );
  await withSession(browser, thao, async (page) => {
    await openCollectionPage(page, ws, own.id);
    // Default selection: the first top-level folder by name.
    await expect(folderRowOf(page, folderA.name).getByTestId("folder-select")).toHaveAttribute(
      "aria-current",
      "true",
    );
    await expect(page.getByTestId("document-row")).toHaveCount(1);
    await expect(docRow(page, inA.name)).toHaveCount(1);
    await expect(docRow(page, inSub.name)).toHaveCount(0);
    await expect(folderCount(page, folderA.name)).toHaveText("1");
    await expect(folderCount(page, sub.name)).toHaveText("1");
    await expect(folderCount(page, folderB.name)).toHaveText("0");
    await expect(page.getByTestId("all-documents").getByTestId("folder-count")).toHaveText("2");

    await selectFolder(page, folderB.name);
    await expect(page.getByTestId("documents-empty")).toHaveText(MSG.emptyFolder);
    await expect(page.getByTestId("drop-zone")).toContainText(`Drop files into ${folderB.name}`);

    await selectAllDocuments(page);
    await expect(page.getByTestId("document-row")).toHaveCount(2);
    await expect(page.getByTestId("drop-zone")).toContainText(MSG.chooseFolder);
    await expect(page.getByTestId("browse-files")).toHaveCount(0);
    await expect(page.getByTestId("upload-files")).toBeDisabled();

    await selectFolder(page, sub.name);
    await expect(docRow(page, inSub.name)).toHaveCount(1);
    await expect(page.getByTestId("document-row")).toHaveCount(1);
  });
  // A collection without documents: "No documents yet." under All documents.
  const empty = await makeCollection(linh, ws, "scope-empty");
  await withSession(browser, thao, async (page) => {
    await openCollectionPage(page, ws, empty.id);
    await expect(page.getByTestId("all-documents")).toHaveAttribute("aria-current", "true");
    await expect(page.getByTestId("documents-empty")).toHaveText(MSG.emptyAll);
    await expect(page.getByTestId("drop-zone")).toContainText(MSG.chooseFolder);
    await expect(page.getByTestId("upload-files")).toBeDisabled();
    await expect(page.getByTestId("all-documents").getByTestId("folder-count")).toHaveText("0");
  });
});

test("AC1 TC-1-10: Preview text opens a dialog with the extracted text, Close and Escape close it", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "ac1-preview");
  const name = `${MARK}-preview.md`;
  const done = await mustReady(thao, loc(folder), name, Buffer.from(buildMd(OVERTIME_VI, true)));
  const extracted = await textOf(thao, ws, col, done.id);
  expect(extracted.truncated).toBe(false);
  expect(extracted.total_characters).toBe(extracted.text.length);
  await withSession(browser, thao, async (page) => {
    await openCollectionPage(page, ws, col);
    await selectFolder(page, folder.name);
    const row = docRow(page, name);
    await row.getByTestId("preview-text").click();
    const dialog = page.getByTestId("preview-text-dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog).toHaveAttribute("role", "dialog");
    await expect(dialog).toContainText(name);
    await expect(dialog.getByTestId("preview-text-content")).toContainText(
      "Quy định làm thêm giờ 2026",
    );
    await expect(dialog.getByTestId("preview-text-content")).toContainText("zqmweekend");
    await expect(dialog.getByTestId("preview-truncated")).toHaveCount(0);
    await dialog.getByRole("button", { name: "Close" }).click();
    await expect(dialog).toBeHidden();
    await row.getByTestId("preview-text").click();
    await expect(dialog).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  });
});

test("AC1 TC-1-11: a text longer than 100 000 characters is previewed truncated with the note", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "ac1-long");
  const name = `${MARK}-long.txt`;
  const done = await mustReady(thao, loc(folder), name, Buffer.from(exactText(150_000)));
  const extracted = await textOf(thao, ws, col, done.id);
  expect(extracted.truncated).toBe(true);
  expect(extracted.text).toHaveLength(100_000);
  expect(extracted.total_characters).toBeGreaterThan(100_000);
  await withSession(browser, thao, async (page) => {
    await openCollectionPage(page, ws, col);
    await selectFolder(page, folder.name);
    await docRow(page, name).getByTestId("preview-text").click();
    const dialog = page.getByTestId("preview-text-dialog");
    await expect(dialog.getByTestId("preview-truncated")).toHaveText(MSG.truncated);
    const shown = await dialog.getByTestId("preview-text-content").evaluate((node) => {
      const element = node as HTMLTextAreaElement;
      return (element.value ?? element.textContent ?? "").length;
    });
    expect(shown).toBeLessThanOrEqual(100_000);
    await page.keyboard.press("Escape");
  });
});

test("AC1 TC-1-12: the Collections list shows the real document total and the existing status texts for none, ready and needs-attention", async ({
  browser,
}) => {
  const own = await makeCollection(linh, ws, "list");
  const folder = await makeFolder(linh, ws, own.id, "list-folder");
  const at: Loc = { ws, col: own.id, folder: folder.id };
  await withSession(browser, thao, async (page) => {
    const statusTexts: string[] = [];
    const readRow = async (): Promise<{ count: string; status: string }> => {
      await page.goto(`/w/${ws}/knowledge`);
      await expect(page.getByTestId("knowledge-page")).toBeVisible();
      const row = rowOf(page, own.name);
      await expect(row).toHaveCount(1);
      return {
        count: (await row.getByTestId("document-count").innerText()).trim(),
        status: (await row.getByTestId("collection-status").innerText()).trim(),
      };
    };
    let state = await readRow();
    expect(state).toEqual({ count: "0", status: "No documents" });
    statusTexts.push(state.status);

    await mustReady(thao, at, `${MARK}-list-ok.txt`, Buffer.from(filler("zqlist", 400)));
    state = await readRow();
    expect(state.count).toBe("1");
    expect(state.status).not.toBe("No documents");
    statusTexts.push(state.status);

    const bad = await mustUpload(thao, at, `${MARK}-list-bad.pdf`, randomJunk());
    const scanned = await mustUpload(thao, at, `${MARK}-list-scan.pdf`, buildScannedPdf(2));
    await waitStatus(thao, ws, own.id, bad.id);
    await waitStatus(thao, ws, own.id, scanned.id);
    state = await readRow();
    expect(state.count).toBe("3");
    expect(state.status).toMatch(/attention/i);
    statusTexts.push(state.status);
    expect(new Set(statusTexts).size, "three different status texts").toBe(3);
  });
  const result = await linh.send("GET", collectionsPath(ws));
  const item = json<{ collections: CollectionItem[] }>(result).collections.find(
    (entry) => entry.id === own.id,
  );
  expect(item?.documents).toEqual({ total: 3, ready: 1, processing: 0, needs_attention: 2 });
});

test("AC1 TC-1-13: Upload files opens the file chooser for the selected folder and uploads the chosen files", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "ac1-chooser");
  const name = `${MARK}-chooser.txt`;
  await withSession(browser, thao, async (page) => {
    await openCollectionPage(page, ws, col);
    await selectFolder(page, folder.name);
    const button = page.getByTestId("upload-files");
    await expect(button).toBeEnabled();
    const chooser = page.waitForEvent("filechooser");
    await button.click();
    const picker = await chooser;
    expect(picker.isMultiple()).toBe(true);
    await picker.setFiles(tempFile(name, filler("zqchoose", 400)));
    await expectStatusText(docRow(page, name), ready(1));

    const viaBrowse = page.waitForEvent("filechooser");
    await page.getByTestId("browse-files").click();
    expect((await viaBrowse).isMultiple()).toBe(true);
    const input = page.getByTestId("file-input");
    await expect(input).toHaveAttribute("type", "file");
    await expect(input).toHaveAttribute("multiple", "");
    await expect(input).toHaveAttribute("accept", ".pdf,.docx,.md,.txt");
    await expect(page.getByLabel("Browse files")).toHaveCount(1);
  });
});

test("AC1 TC-1-14: a folder that holds documents cannot be deleted (409 folder_not_empty, message in the UI) until they are removed", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "ac1-notempty");
  const done = await mustReady(
    thao,
    loc(folder),
    `${MARK}-keeper.txt`,
    Buffer.from(filler("zqkeep", 300)),
  );
  const refused = await linh.send("DELETE", `${collectionsPath(ws)}/${col}/folders/${folder.id}`);
  expect(refused.status, refused.text).toBe(409);
  expect(refused.json).toEqual({ detail: "folder_not_empty" });
  await withSession(browser, linh, async (page) => {
    await openCollectionPage(page, ws, col);
    await page.getByRole("button", { name: `Delete ${folder.name}` }).click();
    await page
      .getByTestId("confirm-folder-delete")
      .getByRole("button", { name: "Delete folder" })
      .click();
    await expect(
      page.getByRole("alert").filter({ hasText: MSG.folderNotEmpty }).first(),
    ).toBeVisible();
    await expect(folderRowOf(page, folder.name)).toHaveCount(1);
  });
  expect((await deleteDoc(thao, ws, col, done.id)).status).toBe(204);
  const removed = await linh.send("DELETE", `${collectionsPath(ws)}/${col}/folders/${folder.id}`);
  expect(removed.status, removed.text).toBe(204);
});

test("AC1 TC-1-15: deleting a collection removes its documents and chunks at once and the stored originals within 60 s", async () => {
  const own = await makeCollection(linh, ws, "wipe");
  const folder = await makeFolder(linh, ws, own.id, "wipe-folder");
  const at: Loc = { ws, col: own.id, folder: folder.id };
  const first = await mustReady(thao, at, `${MARK}-wipe-1.txt`, Buffer.from(filler("zqw1", 600)));
  const second = await mustReady(thao, at, `${MARK}-wipe-2.pdf`, buildPdf([filler("zqw2", 600)]));
  for (const item of [first, second]) {
    expect(chunkRows(item.id), "precondition: chunks exist").toBeGreaterThan(0);
    expect(storedFiles(DEMO_ORG, item.id), "precondition: the original is stored").toBeGreaterThan(
      0,
    );
  }
  const removed = await linh.send("DELETE", `${collectionsPath(ws)}/${own.id}`);
  expect(removed.status, removed.text).toBe(204);
  for (const item of [first, second]) {
    expect(chunkRows(item.id), "chunks are gone at once").toBe(0);
    expect(Number(sql(`select count(*) from documents where id = '${item.id}'`))).toBe(0);
  }
  for (const item of [first, second]) {
    expect(
      await waitStoredGone(DEMO_ORG, item.id, 60_000),
      `original of ${item.name} deleted`,
    ).toBe(true);
  }
});

test("AC1 TC-1-16: the first multi-file upload after a fresh page load uploads every file (no 403 from a CSRF token refresh race)", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "ac1-fresh");
  const failures: string[] = [];
  const statuses: number[] = [];
  for (let attempt = 0; attempt < 4; attempt++) {
    const names = Array.from({ length: 8 }, (_, index) => `${MARK}-fresh-${attempt}-${index}.txt`);
    const paths = names.map((name) => tempFile(name, filler(`zqfresh${attempt}`, 400)));
    await withSession(browser, thao, async (page) => {
      page.on("response", (response) => {
        if (response.request().method() === "POST" && /\/documents$/.test(response.url())) {
          statuses.push(response.status());
        }
      });
      await openCollectionPage(page, ws, col);
      await selectFolder(page, folder.name);
      await chooseFiles(page, paths);
      await expect(page.getByTestId("document-row"))
        .toHaveCount(attempt * 8 + 8, { timeout: 15_000 })
        .catch(() => {
          failures.push(`attempt ${attempt}: not every file was listed`);
        });
      failures.push(...(await rejectionLines(page)));
    });
  }
  expect(failures, `rejections after a fresh load (POST statuses ${statuses.join(",")})`).toEqual(
    [],
  );
  expect(statuses.every((status) => status === 201)).toBe(true);
});

// ---------------------------------------------------------------------------------------------
// AC2 Unsupported format
// ---------------------------------------------------------------------------------------------

test("AC2: setup.exe and old.doc are rejected at once with the supported formats and no request is sent; the valid .txt of the same drop is uploaded", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "ac2-mixed-drop");
  const exe = "setup.exe";
  const doc = "old.doc";
  const txt = `${MARK}-ac2-valid.txt`;
  const paths = [
    tempFile(exe, randomJunk(300)),
    tempFile(doc, randomJunk(300)),
    tempFile(txt, filler("zqac2", 400)),
  ];
  await withSession(browser, thao, async (page) => {
    await openCollectionPage(page, ws, col);
    await selectFolder(page, folder.name);
    const requests = uploadRequests(page);
    await chooseFiles(page, paths);
    // Immediately: no await on the network before the lines show up.
    await expect(page.getByTestId("upload-rejection")).toHaveCount(2);
    const lines = await rejectionLines(page);
    expect([...lines].sort()).toEqual([MSG.unsupported(doc), MSG.unsupported(exe)].sort());
    await expect(page.getByRole("alert").first()).toBeVisible();
    await expect(page.getByRole("alert").first()).toContainText(
      "Supported formats: PDF with text, DOCX, MD, TXT.",
    );
    await expectStatusText(docRow(page, txt), ready(1));
    await expect(docRow(page, exe)).toHaveCount(0);
    await expect(docRow(page, doc)).toHaveCount(0);
    expect(requests.map((request) => request.name)).toEqual([txt]);
    await page.screenshot({ path: `${SCREENSHOTS_33}/ac2-rejections.png`, fullPage: true });
  });
  const listed = await listDocs(thao, ws, col, folder.id);
  expect(listed.map((item) => item.name)).toEqual([txt]);
});

test("AC2 TC-2-2: the API answers 415 unsupported_format for .exe, .doc, .xlsx, .csv and no extension, creates no row, and accepts upper-case extensions", async () => {
  const folder = await makeFolder(linh, ws, col, "ac2-api");
  const body = Buffer.from(filler("zqfmt", 300));
  const rejected = [
    "x.exe",
    "x.doc",
    "table.xlsx",
    "data.csv",
    "archive.zip",
    "page.html",
    "README",
    "pdf",
    "x.pdf.exe",
    "x.exe.txt.bak",
    "SETUP.EXE",
    "doc.DOC",
  ];
  for (const name of rejected) {
    const result = await uploadRaw(thao, loc(folder), name, body);
    expect(result.status, `${name}: ${result.text}`).toBe(415);
    expect(result.json, name).toEqual({ detail: "unsupported_format" });
  }
  expect(await listDocs(thao, ws, col, folder.id), "no row created").toEqual([]);
  const upper = await mustReady(thao, loc(folder), `${MARK}-UPPER.TXT`, body);
  expect(upper.format).toBe("txt");
  const mixed = await mustReady(
    thao,
    loc(folder),
    `${MARK}-Mixed.Md`,
    Buffer.from("# Title\n\nSome text of the note.\n"),
  );
  expect(mixed.format).toBe("md");
});

test("AC2 TC-2-3: file name, empty file and check order: invalid names are 422, empty files 422, format is checked before empty", async () => {
  const folder = await makeFolder(linh, ws, col, "ac2-names");
  const body = Buffer.from(filler("zqnm", 300));
  const bad: { label: string; rawName: string | null }[] = [
    { label: "header missing", rawName: null },
    { label: "invalid percent-encoding", rawName: "%E0%A4%A.txt" },
    { label: "empty after trimming", rawName: "%20%20%20" },
    { label: "empty header", rawName: "" },
    { label: "only a path", rawName: encodeURIComponent("folder/") },
    { label: "256 characters", rawName: `${"a".repeat(252)}.txt` },
    { label: "NUL control character", rawName: "a%00b.txt" },
    { label: "newline control character", rawName: "a%0Ab.txt" },
  ];
  for (const entry of bad) {
    const result = await uploadRaw(thao, loc(folder), null, body, { rawName: entry.rawName });
    expect(result.status, `${entry.label}: ${result.text}`).toBe(422);
    expect(result.json, entry.label).toEqual({ detail: "invalid_file_name" });
  }
  const longest = await uploadRaw(thao, loc(folder), `${"b".repeat(251)}.txt`, body);
  expect(longest.status, "255 characters are valid").toBe(201);

  const empty = await uploadRaw(thao, loc(folder), `${MARK}-empty.txt`, Buffer.alloc(0));
  expect(empty.status, empty.text).toBe(422);
  expect(empty.json).toEqual({ detail: "empty_file" });
  const emptyExe = await uploadRaw(thao, loc(folder), "empty.exe", Buffer.alloc(0));
  expect(emptyExe.status, "format is checked before emptiness").toBe(415);
  const badNameEmpty = await uploadRaw(thao, loc(folder), null, Buffer.alloc(0), { rawName: "" });
  expect(badNameEmpty.status, "the name is checked before the body").toBe(422);
  expect(badNameEmpty.json).toEqual({ detail: "invalid_file_name" });
  const listed = await listDocs(thao, ws, col, folder.id);
  expect(listed.map((item) => item.name)).toEqual([`${"b".repeat(251)}.txt`]);
});

test("AC2 TC-2-4: the UI rejects .xlsx, upper-case .EXE and an empty file with the contract messages; a drop of rejected files only adds no row", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "ac2-ui");
  const names = { xlsx: "table.xlsx", exe: "SETUP.EXE", empty: `${MARK}-empty.txt` };
  const paths = [
    tempFile(names.xlsx, randomJunk(200)),
    tempFile(names.exe, randomJunk(200)),
    tempFile(names.empty, ""),
  ];
  await withSession(browser, thao, async (page) => {
    await openCollectionPage(page, ws, col);
    await selectFolder(page, folder.name);
    const requests = uploadRequests(page);
    await chooseFiles(page, paths);
    await expect(page.getByTestId("upload-rejection")).toHaveCount(3);
    expect([...(await rejectionLines(page))].sort()).toEqual(
      [MSG.unsupported(names.xlsx), MSG.unsupported(names.exe), MSG.empty(names.empty)].sort(),
    );
    await expect(page.getByTestId("document-row")).toHaveCount(0);
    await expect(page.getByTestId("documents-empty")).toHaveText(MSG.emptyFolder);
    // Format and size are checked in the browser; an empty file may be refused by the server (422 empty_file).
    expect(
      requests.map((request) => request.name),
      "no upload request for the unsupported formats",
    ).toEqual(
      requests.filter((request) => request.name === names.empty).map((request) => request.name),
    );
  });
});

// ---------------------------------------------------------------------------------------------
// AC4 Scanned PDF
// ---------------------------------------------------------------------------------------------

test("AC4: a scanned PDF is Not supported with the OCR message, no chunks and a Remove action; Remove asks for confirmation and deletes the row", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "ac4-scan");
  const name = `${MARK}-scan.pdf`;
  const item = await mustUpload(thao, loc(folder), name, buildScannedPdf(2));
  const done = await waitStatus(thao, ws, col, item.id);
  expect(done).toMatchObject({
    status: "not_supported",
    reason: "scanned_pdf",
    page_count: null,
    progress: null,
    format: "pdf",
  });
  const chunks = await thao.send("GET", chunksPath(ws, col, item.id));
  expect(chunks.status, chunks.text).toBe(409);
  expect(chunks.json).toEqual({ detail: "document_not_ready" });
  const text = await thao.send("GET", textPath(ws, col, item.id));
  expect(text.status).toBe(409);
  expect(text.json).toEqual({ detail: "document_not_ready" });
  expect(chunkRows(item.id), "no chunks stored").toBe(0);

  await withSession(browser, thao, async (page) => {
    await openCollectionPage(page, ws, col);
    await selectFolder(page, folder.name);
    const row = docRow(page, name);
    await expect(row).toHaveAttribute("data-status", "not_supported");
    await expect(row.getByTestId("document-status")).toContainText("Not supported");
    await expect(row.getByTestId("document-reason")).toHaveText(MSG.scanned);
    await expect(row.getByTestId("preview-text")).toHaveCount(0);
    const remove = row.getByTestId("remove-document");
    await expect(remove).toHaveAccessibleName(`Remove ${name}`);
    await page.screenshot({ path: `${SCREENSHOTS_33}/ac4-not-supported.png`, fullPage: true });

    // Cancel sends nothing.
    const deletes: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "DELETE") deletes.push(request.url());
    });
    await remove.click();
    const dialog = page.getByTestId("remove-document-dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText(`Remove ${name}?`);
    await expect(dialog).toContainText(MSG.removeBody);
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
    expect(deletes).toEqual([]);
    await expect(row).toHaveCount(1);

    await remove.click();
    await page.getByTestId("confirm-remove-document").click();
    await expect(
      page.getByRole("status").filter({ hasText: `${name} was removed.` }),
    ).toBeVisible();
    await expect(row).toHaveCount(0);
    await expect(folderCount(page, folder.name)).toHaveText("0");
  });
  expect(await getDoc(thao, ws, col, item.id)).toBeUndefined();
  expect(Number(sql(`select count(*) from documents where id = '${item.id}'`))).toBe(0);
});

test("AC4 TC-4-2: the 50 characters per page average decides: a sparse PDF is Not supported, a PDF with some blank pages but enough text overall is Ready", async () => {
  const folder = await makeFolder(linh, ws, col, "ac4-density");
  const sparse = await mustUpload(
    thao,
    loc(folder),
    `${MARK}-sparse.pdf`,
    buildPdf(["Page one", "Page two", "Page three"]),
  );
  const mixed = await mustUpload(
    thao,
    loc(folder),
    `${MARK}-mixed.pdf`,
    buildPdf([filler("zqmix", 400), "", ""]),
  );
  const sparseDone = await waitStatus(thao, ws, col, sparse.id);
  const mixedDone = await waitStatus(thao, ws, col, mixed.id);
  expect(sparseDone).toMatchObject({ status: "not_supported", reason: "scanned_pdf" });
  expect(mixedDone.status).toBe("ready");
  expect(mixedDone.page_count).toBe(3);
  expect(chunkRows(sparse.id)).toBe(0);
  expect(chunkRows(mixed.id)).toBeGreaterThan(0);
});

test("AC4 TC-4-3: upload and removal write audit events with codes only; file names never appear in audit_events", async () => {
  const folder = await makeFolder(linh, ws, col, "ac4-audit");
  const name = `${MARK}-audit-secret-name.txt`;
  const done = await mustReady(thao, loc(folder), name, Buffer.from(filler("zqaudit", 300)));
  const thaoId = userIdOf(ACCOUNT.thao.email);
  expect(auditOf(done.id)).toEqual([
    {
      action: "document.uploaded",
      target_type: "document",
      old_value: null,
      new_value: "txt",
      actor: `user:${thaoId}`,
    },
  ]);
  expect((await deleteDoc(thao, ws, col, done.id)).status).toBe(204);
  expect(auditOf(done.id)).toEqual([
    {
      action: "document.uploaded",
      target_type: "document",
      old_value: null,
      new_value: "txt",
      actor: `user:${thaoId}`,
    },
    {
      action: "document.removed",
      target_type: "document",
      old_value: "txt",
      new_value: null,
      actor: `user:${thaoId}`,
    },
  ]);
  expect(auditRowsContaining(name), "the file name is not audited").toBe(0);
  expect(auditRowsContaining("audit-secret-name")).toBe(0);
});

// ---------------------------------------------------------------------------------------------
// AC5 Normalisation
// ---------------------------------------------------------------------------------------------

type ChunkPair = { nfc: Chunk[]; nfd: Chunk[]; nfcText: string; nfdText: string };

async function uploadPair(
  label: string,
  extension: "md" | "txt" | "docx",
  make: (form: "NFC" | "NFD") => Buffer,
): Promise<ChunkPair> {
  const folder = await makeFolder(linh, ws, col, label);
  const nfcBytes = make("NFC");
  const nfdBytes = make("NFD");
  expect(nfcBytes.equals(nfdBytes), "precondition: the two files differ byte for byte").toBe(false);
  const nfc = await mustReady(thao, loc(folder), `${MARK}-vn-nfc.${extension}`, nfcBytes);
  const nfd = await mustReady(thao, loc(folder), `${MARK}-vn-nfd.${extension}`, nfdBytes);
  expect(nfd.page_count).toBe(nfc.page_count);
  return {
    nfc: await chunksOf(thao, ws, col, nfc.id),
    nfd: await chunksOf(thao, ws, col, nfd.id),
    nfcText: (await textOf(thao, ws, col, nfc.id)).text,
    nfdText: (await textOf(thao, ws, col, nfd.id)).text,
  };
}

function expectIdenticalChunks(pair: ChunkPair): void {
  expect(pair.nfd.length, "same number of chunks").toBe(pair.nfc.length);
  expect(pair.nfc.length).toBeGreaterThan(1);
  expect(JSON.stringify(pair.nfd), "byte-identical chunk lists").toBe(JSON.stringify(pair.nfc));
  expect(Buffer.from(JSON.stringify(pair.nfd)).equals(Buffer.from(JSON.stringify(pair.nfc)))).toBe(
    true,
  );
  expect(pair.nfdText).toBe(pair.nfcText);
  expect(pair.nfcText, "normalised text is NFC").toBe(pair.nfcText.normalize("NFC"));
  for (const chunk of pair.nfd) {
    expect(chunk.text, `chunk ${chunk.ordinal} is NFC`).toBe(chunk.text.normalize("NFC"));
    for (const heading of chunk.heading_path) expect(heading).toBe(heading.normalize("NFC"));
  }
  expectChunkInvariants(pair.nfd, pair.nfdText);
}

test("AC5: the same Vietnamese Markdown document in NFC and NFD produces byte-identical chunks (text, heading path, offsets)", async () => {
  const markdown = buildMd(OVERTIME_VI, true);
  const pair = await uploadPair("ac5-md", "md", (form) => Buffer.from(markdown.normalize(form)));
  expectIdenticalChunks(pair);
  expectSectionsRespected(pair.nfd, OVERTIME_VI);
});

test("AC5 TC-5-2: the same DOCX in NFC and NFD (headings included) produces byte-identical chunks", async () => {
  const pair = await uploadPair("ac5-docx", "docx", (form) =>
    buildDocx(OVERTIME_VI, { vi: true, form }),
  );
  expectIdenticalChunks(pair);
  expectSectionsRespected(pair.nfd, OVERTIME_VI);
});

test("AC5 TC-5-3: the same TXT in NFC and NFD produces byte-identical chunks", async () => {
  const text = [fillerVi("zqt1", 2500), fillerVi("zqt2", 2500)].join("\n\n");
  const pair = await uploadPair("ac5-txt", "txt", (form) => Buffer.from(text.normalize(form)));
  expectIdenticalChunks(pair);
});

// ---------------------------------------------------------------------------------------------
// AC6 Chunk location
// ---------------------------------------------------------------------------------------------

test("AC6: PDF chunks carry the page (1-based), never span two pages and cite like 'Timesheet & Approval Guide — page 4'", async () => {
  const folder = await makeFolder(linh, ws, col, "ac6-pdf");
  const name = `${MARK}-Timesheet & Approval Guide.pdf`;
  const pages = [
    filler("zqpg1", 900),
    filler("zqpg2", 900),
    filler("zqpg3", 2600),
    filler("zqpg4", 3200),
    filler("zqpg5", 800),
  ];
  const done = await mustReady(thao, loc(folder), name, buildPdf(pages));
  expect(done.page_count).toBe(5);
  const chunks = await chunksOf(thao, ws, col, done.id);
  const extracted = (await textOf(thao, ws, col, done.id)).text;
  expectChunkInvariants(chunks, extracted);
  expect(chunkRows(done.id), "every chunk is stored with its doc_id").toBe(chunks.length);
  for (const chunk of chunks) {
    const markers = markersIn(chunk.text);
    expect(markers, "a chunk never spans two pages").toHaveLength(1);
    const expectedPage = Number((markers[0] as string).replace("zqpg", ""));
    expect(chunk.page, `chunk ${chunk.ordinal}`).toBe(expectedPage);
    expect(chunk.heading_path).toEqual([]);
  }
  expect(new Set(chunks.map((chunk) => chunk.page))).toEqual(new Set([1, 2, 3, 4, 5]));
  expect(chunks.filter((chunk) => chunk.page === 4).length).toBeGreaterThanOrEqual(2);
  const citation = `${name.replace(`${MARK}-`, "")} — page ${chunks.find((chunk) => chunk.page === 4)?.page}`;
  expect(citation).toBe("Timesheet & Approval Guide.pdf — page 4");
});

test("AC6 TC-6-2: Markdown chunks carry the heading path (outermost first), text before the first heading has an empty path, and the sections are not mixed", async () => {
  const folder = await makeFolder(linh, ws, col, "ac6-md");
  const done = await mustReady(
    thao,
    loc(folder),
    `${MARK}-Overtime Policy 2026.md`,
    Buffer.from(buildMd(OVERTIME)),
  );
  const chunks = await chunksOf(thao, ws, col, done.id);
  const extracted = (await textOf(thao, ws, col, done.id)).text;
  expectChunkInvariants(chunks, extracted);
  expectSectionsRespected(chunks, OVERTIME);
  const weekend = chunks.filter((chunk) => markersIn(chunk.text).includes("zqmweekend"));
  expect(weekend.length, "3.2 Weekend work is long: several chunks").toBeGreaterThanOrEqual(3);
  for (const chunk of weekend) {
    expect(chunk.heading_path).toEqual([
      "Overtime Policy 2026",
      "3. Approvals",
      "3.2 Weekend work",
    ]);
    expect(chunk.heading_path.at(-1)?.startsWith("3.2")).toBe(true);
  }
  const preamble = chunks.filter((chunk) => markersIn(chunk.text).includes("zqmpre"));
  expect(preamble.length).toBeGreaterThan(0);
  for (const chunk of preamble) expect(chunk.heading_path).toEqual([]);
  expect(chunkRows(done.id)).toBe(chunks.length);
  const citation = `Overtime Policy 2026 — §${(weekend[0]?.heading_path.at(-1) ?? "").split(" ")[0]}`;
  expect(citation).toBe("Overtime Policy 2026 — §3.2");
});

test("AC6 TC-6-3: DOCX chunks carry the heading path of Heading 1-3 styles", async () => {
  const folder = await makeFolder(linh, ws, col, "ac6-docx");
  const done = await mustReady(
    thao,
    loc(folder),
    `${MARK}-Overtime Policy 2026.docx`,
    buildDocx(OVERTIME, { pages: 3 }),
  );
  const chunks = await chunksOf(thao, ws, col, done.id);
  const extracted = (await textOf(thao, ws, col, done.id)).text;
  expectChunkInvariants(chunks, extracted);
  expectSectionsRespected(chunks, OVERTIME);
  const weekend = chunks.filter((chunk) => markersIn(chunk.text).includes("zqmweekend"));
  expect(weekend.length).toBeGreaterThanOrEqual(3);
  expect(weekend[0]?.heading_path).toEqual([
    "Overtime Policy 2026",
    "3. Approvals",
    "3.2 Weekend work",
  ]);
});

test("AC6 TC-6-4: TXT chunks have no page and an empty heading path; offsets index the extracted text; sizes and overlap follow the contract", async () => {
  const folder = await makeFolder(linh, ws, col, "ac6-txt");
  const text = [filler("zqt1", 3000), filler("zqt2", 3000), filler("zqt3", 3000)].join("\n\n");
  const done = await mustReady(thao, loc(folder), `${MARK}-plain.txt`, Buffer.from(text));
  const chunks = await chunksOf(thao, ws, col, done.id);
  const extracted = await textOf(thao, ws, col, done.id);
  expect(extracted.truncated).toBe(false);
  expectChunkInvariants(chunks, extracted.text);
  expect(chunks.length).toBeGreaterThanOrEqual(5);
  for (const chunk of chunks) {
    expect(chunk.page).toBeNull();
    expect(chunk.heading_path).toEqual([]);
    expect(chunk.token_estimate).toBeLessThanOrEqual(560);
  }
  expect(chunks[0]?.char_start).toBe(0);
  expect(chunks.at(-1)?.char_end).toBe(extracted.text.length);
});

// ---------------------------------------------------------------------------------------------
// AC7 Parse errors
// ---------------------------------------------------------------------------------------------

test("AC7: broken.pdf (random bytes) is Failed with a reason and Remove; the valid TXT of the same upload is Ready", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "ac7-pair");
  const broken = `${MARK}-broken.pdf`;
  const valid = `${MARK}-ac7-valid.txt`;
  const paths = [tempFile(broken, randomJunk(4096)), tempFile(valid, filler("zqac7", 400))];
  await withSession(browser, thao, async (page) => {
    await openCollectionPage(page, ws, col);
    await selectFolder(page, folder.name);
    await chooseFiles(page, paths);
    const bad = docRow(page, broken);
    const good = docRow(page, valid);
    await expectStatusText(good, ready(1));
    await expect(bad).toHaveAttribute("data-status", "failed");
    await expect(bad.getByTestId("document-status")).toHaveText("Failed");
    await expect(bad.getByTestId("document-reason")).toHaveText(MSG.corrupt);
    await expect(bad.getByTestId("remove-document")).toHaveAccessibleName(`Remove ${broken}`);
    await expect(bad.getByTestId("preview-text")).toHaveCount(0);
    await expect(good.getByTestId("document-reason")).toHaveCount(0);
    await page.screenshot({ path: `${SCREENSHOTS_33}/ac7-failed.png`, fullPage: true });
    // Remove the failed file.
    await bad.getByTestId("remove-document").click();
    await page.getByTestId("confirm-remove-document").click();
    await expect(
      page.getByRole("status").filter({ hasText: `${broken} was removed.` }),
    ).toBeVisible();
    await expect(bad).toHaveCount(0);
    await expect(good).toHaveCount(1);
  });
  const listed = await listDocs(thao, ws, col, folder.id);
  expect(listed.map((item) => item.name)).toEqual([valid]);
});

test("AC7 TC-7-2: truncated PDF, corrupt DOCX and a renamed binary are Failed (corrupt_file); the other files and the API are unaffected", async ({
  request,
}) => {
  const folder = await makeFolder(linh, ws, col, "ac7-kinds");
  const good = Buffer.from(filler("zqgood", 400));
  const pdf = buildPdf([filler("zqtr1", 800), filler("zqtr2", 800)]);
  const cases = [
    {
      name: `${MARK}-truncated.pdf`,
      bytes: pdf.subarray(0, Math.floor(pdf.length * 0.5)),
      reason: "corrupt_file",
    },
    { name: `${MARK}-corrupt.docx`, bytes: randomJunk(4096), reason: "corrupt_file" },
    {
      name: `${MARK}-renamed-setup.pdf`,
      bytes: Buffer.concat([Buffer.from("MZ"), randomJunk(8192)]),
      reason: "corrupt_file",
    },
    {
      name: `${MARK}-zip-no-docx.docx`,
      bytes: Buffer.from("PK\u0003\u0004 this is not a real archive"),
      reason: "corrupt_file",
    },
  ];
  const queued = await Promise.all(
    [
      ...cases.map((entry) => ({ ...entry, kind: "bad" })),
      { name: `${MARK}-ac7-good.txt`, bytes: good, reason: "", kind: "good" },
    ].map(async (entry) => ({
      entry,
      item: await mustUpload(thao, loc(folder), entry.name, entry.bytes),
    })),
  );
  for (const { entry, item } of queued) {
    const done = await waitStatus(thao, ws, col, item.id);
    if (entry.kind === "good") {
      expect(done.status, entry.name).toBe("ready");
    } else {
      expect(done.status, entry.name).toBe("failed");
      expect(done.reason, entry.name).toBe(entry.reason);
      expect(done.page_count).toBeNull();
      const chunks = await thao.send("GET", chunksPath(ws, col, item.id));
      expect(chunks.status).toBe(409);
      expect(chunkRows(item.id)).toBe(0);
    }
  }
  expect((await request.get("/api/healthz")).status()).toBe(200);
});

test("AC7 TC-7-3: a password-protected PDF is Failed (password_protected) with its reason line", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "ac7-password");
  const name = `${MARK}-protected.pdf`;
  const item = await mustUpload(thao, loc(folder), name, buildPasswordPdf());
  const done = await waitStatus(thao, ws, col, item.id);
  expect(done).toMatchObject({ status: "failed", reason: "password_protected" });
  await withSession(browser, thao, async (page) => {
    await openCollectionPage(page, ws, col);
    await selectFolder(page, folder.name);
    await expect(docRow(page, name).getByTestId("document-reason")).toHaveText(MSG.password);
    await expect(docRow(page, name).getByTestId("remove-document")).toBeVisible();
  });
});

test("AC7 TC-7-4: a DOCX zip bomb (small file, more than 250 MB unzipped) is Failed (file_too_complex) and the API stays up", async ({
  request,
}) => {
  const folder = await makeFolder(linh, ws, col, "ac7-bomb");
  const bomb = buildZipBombDocx(300);
  expect(bomb.length, "precondition: the file itself is small").toBeLessThan(5 * 1024 * 1024);
  const item = await mustUpload(thao, loc(folder), `${MARK}-bomb.docx`, bomb);
  const done = await waitStatus(thao, ws, col, item.id);
  expect(done).toMatchObject({ status: "failed", reason: "file_too_complex" });
  expect((await request.get("/api/healthz")).status()).toBe(200);
  const next = await mustReady(
    thao,
    loc(folder),
    `${MARK}-after-bomb.txt`,
    Buffer.from(filler("zqafter", 300)),
  );
  expect(next.status).toBe("ready");
});

test("AC7 TC-7-4b: a DOCX whose XML part alone is larger than 50 MiB (60 MB, small file) is Failed (file_too_complex) and the API stays up", async ({
  request,
}) => {
  const folder = await makeFolder(linh, ws, col, "ac7-bomb-xml");
  const bomb = buildZipBombDocx(60);
  expect(bomb.length, "precondition: the file itself is small").toBeLessThan(2 * 1024 * 1024);
  const item = await mustUpload(thao, loc(folder), `${MARK}-bomb-xml.docx`, bomb);
  const done = await waitStatus(thao, ws, col, item.id);
  expect(done).toMatchObject({ status: "failed", reason: "file_too_complex" });
  expect((await request.get("/api/healthz")).status()).toBe(200);
});

test("AC7 TC-7-5: no text and an unrecognised encoding are Failed with their reasons; the other files are unaffected", async () => {
  const folder = await makeFolder(linh, ws, col, "ac7-text");
  const blankTxt = await mustUpload(
    thao,
    loc(folder),
    `${MARK}-blank.txt`,
    Buffer.from("   \n\n \t \n"),
  );
  const emptyDocx = await mustUpload(thao, loc(folder), `${MARK}-empty.docx`, buildEmptyDocx());
  const binaryTxt = await mustUpload(
    thao,
    loc(folder),
    `${MARK}-binary.txt`,
    Buffer.from(
      Array.from({ length: 4096 }, (_, index) => (index % 2 === 0 ? 0xff : 0xfe + (index % 3))),
    ),
  );
  const fine = await mustUpload(
    thao,
    loc(folder),
    `${MARK}-fine.txt`,
    Buffer.from(filler("zqfine", 300)),
  );
  const blankDone = await waitStatus(thao, ws, col, blankTxt.id);
  const docxDone = await waitStatus(thao, ws, col, emptyDocx.id);
  const binaryDone = await waitStatus(thao, ws, col, binaryTxt.id);
  const fineDone = await waitStatus(thao, ws, col, fine.id);
  expect(blankDone).toMatchObject({ status: "failed", reason: "no_text" });
  expect(docxDone).toMatchObject({ status: "failed", reason: "no_text" });
  expect(binaryDone.status).toBe("failed");
  expect(["unreadable_encoding", "no_text"]).toContain(binaryDone.reason);
  expect(fineDone.status).toBe("ready");
});

// ---------------------------------------------------------------------------------------------
// AC9 Matches the design
// ---------------------------------------------------------------------------------------------

test("AC9: the Collection detail shows the header, the folder list with counts, the drop zone and the document table of the CollectionDetail artboard", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "ac9-design");
  const names = [`${MARK}-ac9-a.txt`, `${MARK}-ac9-b.md`, `${MARK}-ac9-c.pdf`];
  await mustReady(thao, loc(folder), names[0] as string, Buffer.from(filler("zqx1", 500)));
  await mustReady(thao, loc(folder), names[1] as string, Buffer.from(buildMd(OVERTIME)));
  await mustReady(thao, loc(folder), names[2] as string, buildPdf([filler("zqx3", 500)]));
  const total = await handbookTotal();
  await withSession(browser, thao, async (page) => {
    const seen = watch(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await openCollectionPage(page, ws, col);
    await expect(page).toHaveTitle("Employee Handbook · ei-ai");

    // Header: breadcrumb, title, access badge, settings and the primary upload button.
    const detail = page.getByTestId("collection-detail");
    await expect(detail).toContainText("Knowledge");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Employee Handbook");
    await expect(detail).toContainText("Authenticated");
    await expect(page.getByTestId("collection-settings")).toBeVisible();
    const upload = page.getByTestId("upload-files");
    await expect(upload).toHaveText("Upload files");
    await expect(upload).toBeVisible();

    // Default selection: the first top-level folder by name.
    await expect(folderRowOf(page, "Benefits").getByTestId("folder-select")).toHaveAttribute(
      "aria-current",
      "true",
    );
    await expect(upload).toBeEnabled();

    // Folder list: All documents with the total, folders with counts, New folder.
    const panel = page.getByTestId("folders-panel");
    await expect(page.getByTestId("all-documents")).toContainText("All documents");
    await expect(page.getByTestId("all-documents").getByTestId("folder-count")).toHaveText(
      String(total),
    );
    for (const topLevel of ["Benefits", "Onboarding & offboarding", "Policies", "Templates"]) {
      await expect(folderRowOf(page, topLevel)).toHaveCount(1);
      await expect(folderCount(page, topLevel)).toHaveText(/^\d+$/);
    }
    await expect(panel.getByRole("button", { name: "New folder" })).toBeVisible();

    // Policies (seed folder, read only): drop zone and empty table.
    await selectFolder(page, "Policies");
    const zone = page.getByTestId("drop-zone");
    await expect(zone).toContainText("Drop files into Policies");
    await expect(zone).toContainText(MSG.dropHint);
    await expect(zone.getByTestId("browse-files")).toHaveText("Browse");
    await expect(page.getByTestId("file-input")).toHaveAttribute("accept", ".pdf,.docx,.md,.txt");

    // Own folder with three documents: table columns, cells and actions.
    await selectFolder(page, folder.name);
    await expect(page.getByTestId("documents-table").getByRole("columnheader")).toHaveText([
      ...MSG.headers,
    ]);
    await expect(page.getByTestId("document-row")).toHaveCount(3);
    for (const name of names) {
      const row = docRow(page, name);
      await expect(row.getByTestId("document-status")).toHaveText(/^Ready · \d+ pages?$/);
      await expect(row.getByTestId("document-updated")).toHaveText("Today · Thao Nguyen");
      await expect(row.getByTestId("preview-text")).toHaveText("Preview text");
    }
    await expect(page.getByText("Replace", { exact: true })).toHaveCount(0);
    // The "Ask this collection" panel is no longer out of scope: EA-37 adds it (not asserted here).
    await page.screenshot({ path: `${SCREENSHOTS_33}/ac9-collection-detail.png`, fullPage: true });
    expect(withoutStatuses(seen.problems, [])).toEqual([]);

    // Narrow screen: the page still shows the drop zone and the table without horizontal overflow of the body.
    await page.setViewportSize({ width: 820, height: 900 });
    await expect(page.getByTestId("drop-zone")).toBeVisible();
    await expect(page.getByTestId("documents-table")).toBeVisible();
    await page.screenshot({
      path: `${SCREENSHOTS_33}/ac9-collection-detail-820.png`,
      fullPage: true,
    });
  });
});
