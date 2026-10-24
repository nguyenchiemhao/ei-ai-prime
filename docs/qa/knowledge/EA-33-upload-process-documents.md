# EA-33 [KB-02] Upload and process PDF/DOCX/MD/TXT documents into normalised chunks

Black-box QA from the ticket and its test contract. Admin UI in English.

## Purpose and preconditions

- Upload PDF (with a text layer), DOCX, MD and TXT files into a Folder of a Collection; each file is processed in the background (Queued, Processing n %, Ready · N pages, Failed with a reason, Not supported for scanned PDFs) and stored as normalised chunks with page or heading path and offsets. Preview text, Remove, folder and collection counts, audit.
- Rules under test: formats and the 50 MB limit are refused with the contract messages; permission (Knowledge Editor, Workspace Admin, Builder upload; Viewer, Reviewer, Developer get 403); tenant isolation (foreign ids answer an identical 404); identity only from the session; file names and text never reach logs or audit; NFC and NFD give byte-identical chunks.
- Stack: `npm run up -- --no-model`, then `npm run seed`. Admin URL `http://localhost:<ADMIN_PORT>` (3100 in this repo's `.env`), API under `/api`, direct API at `http://127.0.0.1:8000` (raw socket checks). Accounts: Linh Tran (admin), Thao Nguyen (knowledge editor), Minh Pham (builder), Son Hoang (viewer), Hà Vũ (reviewer), Quang Le (developer), Ngân Trịnh (Sông Hàn Retail); shared password `EI_AI_SEED_PASSWORD` (see `docs/dev/seed-data.md`).
- Test data: the specs build their own files (text PDF, scanned PDF, DOCX, zip bomb, password-protected PDF, random bytes) in `e2e/support/ea33.ts`, no library needed. Every folder, collection and file name carries `qa-EA33-<run>`; uploads go only into own folders of "Employee Handbook" or own collections (the seed folders such as Policies are only read). Teardown removes documents (API), folders, collections and audit rows; `afterAll` compares the row counts of `documents`, `document_chunks`, `folders`, `collections` and the document/folder/collection audit events with the counts before the run and checks that no row holds the marker.
- Do not run two QA specs of different tickets at once.

## How to run

```
npm run e2e -- e2e/knowledge/EA-33-upload-process-documents.spec.ts          # fast tier, 36 tests, about 1 min
npm run e2e -- e2e/knowledge/EA-33-upload-process-documents-access.spec.ts   # AC8 and the attack list, 12 tests
npm run e2e:full -- e2e/knowledge/EA-33-upload-process-documents-limits.spec.ts   # @slow: AC3, exact 50 MB
EA33_QUOTA=1 npm run e2e:full -- e2e/knowledge/EA-33-upload-process-documents-limits.spec.ts -g TC-3-4   # opt-in, about 1 GB
npm run e2e:perf -- e2e/knowledge/EA-33-upload-process-documents-perf.spec.ts   # @perf, NFR 50-page PDF <= 120 s
EA33_EXPLORE_DIR=.work/EA-33/explore-files npm run e2e -- e2e/knowledge/EA-33-upload-process-documents-explore-files.spec.ts   # writes sample files for the browser flows
node e2e/knowledge/scripts/EA-33-upload-process-documents-explore-data.mjs setup     # folder qa-EA33-explore with 3 text files (prints JSON)
node e2e/knowledge/scripts/EA-33-upload-process-documents-explore-data.mjs bulk 30   # 30 small files for a performance trace
node e2e/knowledge/scripts/EA-33-upload-process-documents-explore-data.mjs cleanup  # removes what setup/bulk created
```

The specs are serial (shared state): the first failure skips the rest of that file.

## Cases

| TC | AC | Type | Steps | Expected | Spec or script |
|---|---|---|---|---|---|
| TC-1-1 | AC1 | automated | Thao: own folder, Browse 5 files (3-page PDF, DOCX, MD, TXT, 1-page PDF) | 5 rows, each Ready · N pages without a reload; sizes, "Today · Thao Nguyen", folder and All documents counts; Collections list total | spec `AC1:` |
| TC-1-2 | AC1 | automated | API: 3 sequential TXT uploads, filter by folder | 201 queued DocumentItem keys; newest first; uploader | `AC1 TC-1-2` |
| TC-1-3 | AC1 | automated | Vietnamese name with `&`, path part in the name | stored and shown as the base name | `AC1 TC-1-3` |
| TC-1-4 | AC1 | automated | Drop a file on the drop zone | uploaded into the selected folder | `AC1 TC-1-4` |
| TC-1-5 | AC1 | automated | 10 parallel API uploads | all Ready | `AC1 TC-1-5` |
| TC-1-6, 1-7 | AC1 | automated | Sizes 500 B / 14 KB / 1.2 MB; page counts for TXT, MD, DOCX (with and without Pages), PDF | contract formats; 1, 2, 2, 7, estimate, 6 | `AC1 TC-1-6`, `TC-1-7` |
| TC-1-8 | AC1 | automated | Delay the POST by 2 s | "Uploading…" until accepted | `AC1 TC-1-8` |
| TC-1-9 | AC1 | automated | Own collection: folders, child folder, All documents | scoping, counts, empty texts, default selection, disabled Upload files | `AC1 TC-1-9` |
| TC-1-10, 1-11 | AC1 | automated | Preview text (short and 150 000 characters), Close, Escape | dialog, truncation note | `AC1 TC-1-10`, `TC-1-11` |
| TC-1-12 | AC1 | automated | Collections list with none, ready, failed + scanned documents | counts 0, 1, 3; three different status texts | `AC1 TC-1-12` |
| TC-1-13 | AC1 | automated | Upload files and Browse open the chooser | multiple, accept list, label "Browse files" | `AC1 TC-1-13` |
| TC-1-14, 1-15 | AC1 | automated | Delete a folder with documents; delete a collection with documents | 409 folder_not_empty + UI message; documents, chunks at once, originals within 60 s | `AC1 TC-1-14`, `TC-1-15` |
| TC-1-16 | AC1 | automated | Four fresh page loads, 8 files each | every file uploaded (regression guard for the CSRF refresh race, see bug Q1-1) | `AC1 TC-1-16` |
| TC-1-17..20 | AC1 | exploratory | Duplicates, 25 files, reload while processing, BOM/UTF-16 text | flows 3-5 below | flows below |
| TC-2-1..4 | AC2 | automated | `.exe`, `.doc`, `.xlsx`, upper-case, empty file in the UI; 12 names and 8 bad names through the API | rejection lines, 415/422 codes, check order, no row | `AC2:`, `AC2 TC-2-2..4` |
| TC-3-1..3 | AC3 | automated @slow | 52 428 801 bytes in the UI and API; exactly 52 428 800; Content-Length at the limit | message / 413 file_too_large; 201; removal in any status | limits spec `AC3`, `TC-3-2`, `TC-3-3` |
| TC-3-4 | AC3 | automated @slow, opt-in | Fill the Organization to 1 GB | 413 storage_quota_exceeded; UI storage-full line | `AC3 TC-3-4` |
| TC-4-1..3 | AC4 | automated | Scanned PDF: status, message, no chunks, Remove flow; density boundary; audit rows | contract texts; 409 document_not_ready; audit codes only | `AC4:`, `AC4 TC-4-2`, `TC-4-3` |
| TC-5-1..3 | AC5 | automated | NFC and NFD pairs of MD, DOCX, TXT | identical chunk JSON, NFC text | `AC5:`, `AC5 TC-5-2`, `TC-5-3` |
| TC-6-1..4 | AC6 | automated | PDF pages, MD and DOCX heading paths, TXT | page / heading_path / offsets, no mixed sections, size and overlap | `AC6:`, `AC6 TC-6-2..4` |
| TC-7-1..5 | AC7 | automated | Random-bytes PDF with a valid TXT; truncated PDF, corrupt DOCX, renamed binary; password PDF; zip bomb; empty text and bad encoding | Failed with the contract reason; others Ready; API up | `AC7:`, `AC7 TC-7-2..5` |
| TC-7-6 | AC7 | exploratory | Restart the API while files are queued; wait 2 minutes | Failed "Processing was interrupted…" (flow 6) | flow 6 |
| TC-8-1..4 | AC8 | automated | Viewer UI and API; Builder, Editor, Admin; Reviewer, Developer; no session, bad CSRF; 50 MB announced | No access page; 403 forbidden before ids; 401; 403 at once | access spec `AC8:`, `TC-8-2..4` |
| TC-9-1 | AC9 | automated | Header, folder list, drop zone, table columns, no Replace / Ask panel | as the contract; console clean | `AC9:` |
| TC-9-2..5 | AC9 | exploratory | Artboard comparison, keyboard, contrast, narrow screen (flow 1, 2) | see report | flows below |
| TC-A-1..8 | attacks | automated | Cross-Organization and cross-Workspace ids, other collection ids, org params, path traversal, renamed binary, logs and audit, Content-Length lie | 404 identical to unknown ids; ignored params; no leaks; 413 | access spec `Attack TC-A-1..8` |
| TC-N-1 | NFR | automated @perf | 50-page text PDF | Ready within 120 s | perf spec |

## Exploratory flows (Chrome DevTools, desktop 1440 px)

1. Design comparison. Open `file:///.../docs/design/canvas/CollectionDetail.dc.html` and the live collection side by side (sign in as Thao Nguyen, open Employee Handbook, select a folder with documents). Compare header, folder list, drop zone, table columns, status colours (Ready green, Processing blue with bar, Not supported orange with a tinted row), action style (links) and spacing. Ignore XLSX/CSV, Replace and the `.doc` row. (The "Ask this collection" panel was added by EA-37; the AC9 spec no longer asserts its absence.)
2. Keyboard and dialogs. Tab to Upload files, Browse, a Preview text button; press Enter; check focus lands in the dialog on Close, Tab stays inside, Escape closes and focus returns to the opening button. Repeat with Remove on a Failed row (Cancel, Escape, confirm).
3. Many files. Run `explore-data.mjs setup`, write the sample files with the explore-files spec, select folder `qa-EA33-explore`, Browse the 25 files of `many/`; every row appears, none is lost, no "was not uploaded" line.
4. Fresh load multi-file upload. Reload the page, select the folder, Browse 5 files at once; no "was not uploaded. Try again." line and no 403 in the network list (known bug Q1-1).
5. Odd encodings. Upload `-bom.txt`, `-utf16.txt`, `-vi-nfd.txt`; each is Ready and Preview text shows readable Vietnamese.
6. Interrupted processing. Upload three 30 MB TXT files, run `docker compose restart api` at once, wait 2 minutes, select the folder again; the files that were waiting show Failed with "Processing was interrupted. Remove the file and upload it again." and the Collections list counts them as needing attention.
7. Console, network and performance. After flows 1-4: console has no errors apart from deliberate 4xx; no request over 1 s; performance trace of a reload with 17 rows (LCP about 0.4 s, CLS 0); Lighthouse accessibility 100.
8. Cleanup. `explore-data.mjs cleanup`; confirm `SELECT count(*) FROM documents` and `document_chunks` are back to the numbers before the run.

## Round 2 additions (recheck)

Stored originals are encrypted (`/var/lib/ei-ai/files/<org_id>/<file_id>.bin`, `file_id` from `SELECT file_id FROM documents WHERE id = ...`); helpers `fileIdOf`, `storedFiles`, `storedHeader`, `plaintextHits` in `e2e/support/ea33.ts`.

| TC | AC | automated / exploratory | steps | expected | spec |
|---|---|---|---|---|---|
| TC-A-9 | attack | automated | upload `<marker>-disk.txt` (marker x20), Ready, preview, `grep -rl marker /var/lib/ei-ai/files`, read the `.bin` header, Remove | preview shows the marker; grep finds nothing; file only under the caller's org dir; starts `45494101`, size +32; gone within seconds | EA-33-upload-process-documents-access.spec.ts |
| TC-7-4b | AC7 | automated | DOCX with a 60 MB XML part (small file) | Failed `file_too_complex`, API up | EA-33-upload-process-documents.spec.ts |
| TC-R2-1 | AC1 (Q1-1) | automated | 8 fresh loads on a slow network, Browse 5 files each | all 40 POST 201, no rejection line | EA-33-upload-process-documents-recheck.spec.ts |
| TC-R2-2 | AC1 (Q1-2) | automated | upload 3 files, `docker compose restart api` | no "Something went wrong", 3 rows, statuses move on, no reload | recheck spec |
| TC-R2-3 | AC9 (Q1-3) | automated | computed styles at 1440 px | Ready green, Failed/Not supported rows tinted, Remove a text link, one-line drop zone | recheck spec |
| TC-R2-4 | AC1 (Q1-4) | automated | first POST answered 403 (route), upload the same file again | the "was not uploaded" line disappears | recheck spec |

Run: `npm run e2e -- e2e/knowledge/EA-33-upload-process-documents-recheck.spec.ts` (restarts the API container).
Exploration in round 2 was run as these Playwright specs (Chrome DevTools MCP tools were not available to the agent).
