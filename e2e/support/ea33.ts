// EA-33 (KB-02): helpers of the document upload specs. Black-box only: the admin origin (UI + /api
// proxy), the direct API port for raw socket checks, psql as the database superuser, `docker compose`
// for the API logs and the stored originals. Builds on ./ea22, ./ea23, ./ea32 and ./ea94 (seeded accounts).
// Everything a run creates carries the marker `qa-EA33-<run>` (folder names, collection names, file
// names), so cleanupAll() and markerRows() can find it. Test files are built here (PDF, DOCX, ZIP writers
// need no library): the product source is never read.
//
// Draft location: .work/EA-33/e2e-draft/support/ea33.ts; the `run` mode moves it to e2e/support/ea33.ts.
import { createHash, randomBytes } from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { deflateRawSync } from "node:zlib";
import { expect, request as pwRequest, type Locator, type Page } from "@playwright/test";
import {
  ADMIN,
  ADMIN_ORIGIN,
  DEMO_ORG,
  ROOT,
  RUN,
  ApiSession,
  compose,
  escapeRegExp,
  rows,
  sleep,
  sql,
  type ApiResult,
} from "./ea22";
import { collectionsPath, json, type CollectionItem, type FolderItem } from "./ea32";
import { sessionFor } from "./ea94";

export const MARK = `qa-EA33-${RUN}`;
export const SCREENSHOTS_33 = path.join(ROOT, ".work", "EA-33", "screenshots");
export const TMP_DIR = path.join(ROOT, ".work", "EA-33", "tmp", RUN);
export const API_DIRECT = { host: "127.0.0.1", port: Number(process.env.API_PORT ?? "8000") };
export const MB = 1024 * 1024;
const RUN_STARTED = new Date(Date.now() - 5000).toISOString();
export const LIMIT_BYTES = 52_428_800;

// ---------------------------------------------------------------------------------------------
// Accounts (docs/dev/seed-data.md; the shared password is read by seedPassword() of ea94)
// ---------------------------------------------------------------------------------------------

export const ACCOUNT = {
  linh: { email: "linh.tran@mekongdevworks.example", name: "Linh Tran" },
  thao: { email: "thao.nguyen@mekongdevworks.example", name: "Thao Nguyen" },
  minh: { email: "minh.pham@mekongdevworks.example", name: "Minh Pham" },
  son: { email: "son.hoang@mekongdevworks.example", name: "Son Hoang" },
  ha: { email: "ha.vu@mekongdevworks.example", name: "Hà Vũ" },
  quang: { email: "quang.le@mekongdevworks.example", name: "Quang Le" },
  ngan: { email: "ngan.trinh@songhanretail.example", name: "Ngân Trịnh" },
} as const;
export type Who = keyof typeof ACCOUNT;

export const SONGHAN_ORG = "0192a000-0000-7000-8000-00000000ea94";

// ---------------------------------------------------------------------------------------------
// Copy of the contract (exact strings of the admin UI)
// ---------------------------------------------------------------------------------------------

export const SUPPORTED = "Supported formats: PDF with text, DOCX, MD, TXT.";
export const MSG = {
  unsupported: (name: string) =>
    `${name} was not uploaded: this format is not supported. ${SUPPORTED}`,
  tooLarge: (name: string) => `${name} was not uploaded: files can be up to 50 MB.`,
  empty: (name: string) => `${name} was not uploaded: the file is empty.`,
  storageFull: (name: string) =>
    `${name} was not uploaded: your organization's storage is full (1 GB).`,
  badName: (name: string) => `${name} was not uploaded: the file name is not valid.`,
  other: (name: string) => `${name} was not uploaded. Try again.`,
  scanned: "Scanned PDF without text. Text recognition (OCR) is planned for a later release.",
  corrupt: "The file could not be read. It may be damaged.",
  password: "The file is password-protected.",
  noText: "The file contains no text.",
  encoding:
    "The text encoding could not be recognised. Save the file as UTF-8 and upload it again.",
  tooComplex: "The file is too complex to process.",
  processing: "Something went wrong while processing the file.",
  interrupted: "Processing was interrupted. Remove the file and upload it again.",
  dropHint: "PDF with text, DOCX, MD, TXT · up to 50 MB each",
  chooseFolder: "Choose a folder to upload files.",
  emptyFolder: "No documents in this folder yet.",
  emptyAll: "No documents yet.",
  removeBody: "The file and its extracted text are deleted.",
  truncated: "Showing the first 100,000 characters.",
  folderNotEmpty: "Remove its subfolders and documents first.",
  headers: ["Document", "Status", "Size", "Updated", "Actions"],
} as const;

export const SUPPORTED_EXTENSIONS = [".pdf", ".docx", ".md", ".txt"];

export const REASON_TEXT: Record<string, string> = {
  scanned_pdf: MSG.scanned,
  corrupt_file: MSG.corrupt,
  password_protected: MSG.password,
  no_text: MSG.noText,
  unreadable_encoding: MSG.encoding,
  file_too_complex: MSG.tooComplex,
  processing_error: MSG.processing,
  interrupted: MSG.interrupted,
};

/** The size cell of the contract: "N B", "N KB" (1 KB = 1024 B, rounded) or "N.N MB". */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < MB) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / MB).toFixed(1)} MB`;
}

// ---------------------------------------------------------------------------------------------
// API shapes
// ---------------------------------------------------------------------------------------------

export type DocStatus = "queued" | "processing" | "ready" | "failed" | "not_supported";
export type DocumentItem = {
  id: string;
  folder_id: string;
  name: string;
  format: "pdf" | "docx" | "md" | "txt";
  size_bytes: number;
  status: DocStatus;
  progress: number | null;
  reason: string | null;
  page_count: number | null;
  uploaded_by: { id: string; display_name: string } | null;
  created_at: string;
  updated_at: string;
};
export const DOCUMENT_KEYS = [
  "created_at",
  "folder_id",
  "format",
  "id",
  "name",
  "page_count",
  "progress",
  "reason",
  "size_bytes",
  "status",
  "updated_at",
  "uploaded_by",
];
export type Chunk = {
  ordinal: number;
  text: string;
  page: number | null;
  heading_path: string[];
  char_start: number;
  char_end: number;
  token_estimate: number;
};
export const CHUNK_KEYS = [
  "char_end",
  "char_start",
  "heading_path",
  "ordinal",
  "page",
  "text",
  "token_estimate",
];
export type TextBody = { text: string; truncated: boolean; total_characters: number };
export type FolderItem33 = FolderItem & { document_count: number };
export type Loc = { ws: string; col: string; folder: string };
export const TERMINAL: DocStatus[] = ["ready", "failed", "not_supported"];

export function docsPath(ws: string, col: string): string {
  return `${collectionsPath(ws)}/${col}/documents`;
}
export function uploadPath(loc: Loc): string {
  return `${collectionsPath(loc.ws)}/${loc.col}/folders/${loc.folder}/documents`;
}

// ---------------------------------------------------------------------------------------------
// Sessions and tracked writes
// ---------------------------------------------------------------------------------------------

export async function apiOf(who: Who): Promise<ApiSession> {
  return sessionFor(ACCOUNT[who].email);
}

type Creator = { api: ApiSession; ws: string; col: string };
const trackedDocs = new Map<string, Creator>();
const trackedFolders: { id: string; api: ApiSession; ws: string; col: string }[] = [];
const trackedCollections = new Map<string, { api: ApiSession; ws: string }>();
const everDocIds = new Set<string>();

export function trackCollection(id: string, ws: string, api: ApiSession): void {
  trackedCollections.set(id, { api, ws });
}

/** Id list of every document, folder and collection this run created (for audit cleanup). */
export function createdIds(): string[] {
  return [
    ...everDocIds,
    ...trackedFolders.map((folder) => folder.id),
    ...trackedCollections.keys(),
  ];
}

/** Creates a folder `<MARK>-<label>` and registers it for cleanup. */
export async function makeFolder(
  api: ApiSession,
  ws: string,
  col: string,
  label: string,
  parentId: string | null = null,
): Promise<FolderItem33> {
  const body: Record<string, unknown> = { name: `${MARK}-${label}` };
  if (parentId) body.parent_id = parentId;
  const result = await api.send("POST", `${collectionsPath(ws)}/${col}/folders`, { json: body });
  expect(result.status, result.text).toBe(201);
  const folder = json<FolderItem33>(result);
  trackedFolders.push({ id: folder.id, api, ws, col });
  return folder;
}

/** Creates a collection `<MARK> <label>` (Authenticated) and registers it for cleanup. */
export async function makeCollection(
  api: ApiSession,
  ws: string,
  label: string,
): Promise<CollectionItem> {
  const result = await api.send("POST", collectionsPath(ws), {
    json: { name: `${MARK} ${label}`, subtitle: null, access_level: "authenticated", groups: [] },
  });
  expect(result.status, result.text).toBe(201);
  const item = json<CollectionItem>(result);
  trackCollection(item.id, ws, api);
  return item;
}

// ---------------------------------------------------------------------------------------------
// Upload and read API calls
// ---------------------------------------------------------------------------------------------

export type UploadOptions = {
  /** "jar" (default): X-CSRF-Token from the cookie jar; "none": no header; else a literal value. */
  csrf?: "jar" | "none" | string;
  /** Replaces X-File-Name verbatim (already encoded); null sends no header. */
  rawName?: string | null;
  query?: string;
  headers?: Record<string, string>;
  /** Replaces the cookies of the session for this call. */
  cookies?: Record<string, string>;
  /** Content-Type of the body (default application/octet-stream). */
  contentType?: string;
};

/** POST raw file bytes through the admin origin. A 201 is tracked for cleanup. */
export async function uploadRaw(
  api: ApiSession,
  loc: Loc,
  name: string | null,
  body: Buffer,
  options: UploadOptions = {},
): Promise<ApiResult> {
  const headers: Record<string, string> = {
    "content-type": options.contentType ?? "application/octet-stream",
    origin: ADMIN_ORIGIN,
    ...options.headers,
  };
  const rawName = options.rawName === undefined ? name : options.rawName;
  if (rawName !== null) {
    headers["x-file-name"] =
      options.rawName === undefined ? encodeURIComponent(rawName ?? "") : rawName;
  }
  const cookies = options.cookies ?? Object.fromEntries(api.jar);
  if (Object.keys(cookies).length > 0) {
    headers.cookie = Object.entries(cookies)
      .map(([key, value]) => `${key}=${value}`)
      .join("; ");
  }
  const csrf = options.csrf ?? "jar";
  if (csrf === "jar") {
    const token = api.jar.get("ei_csrf");
    if (token) headers["x-csrf-token"] = token;
  } else if (csrf !== "none") {
    headers["x-csrf-token"] = csrf;
  }
  const apiPath = `${uploadPath(loc)}${options.query ?? ""}`;
  const context = await pwRequest.newContext({ baseURL: ADMIN });
  try {
    const response = await context.fetch(`${ADMIN}${apiPath}`, {
      method: "POST",
      headers,
      data: body,
      maxRedirects: 0,
      failOnStatusCode: false,
      timeout: 180_000,
    });
    const text = await response.text();
    let parsed: unknown = null;
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
    const result: ApiResult = {
      method: "POST",
      path: apiPath,
      status: response.status(),
      headers: response.headers(),
      setCookies: [],
      text,
      json: parsed,
      submitted: [],
    };
    if (result.status === 201) {
      const item = parsed as DocumentItem;
      trackedDocs.set(item.id, { api, ws: loc.ws, col: loc.col });
      everDocIds.add(item.id);
    }
    return result;
  } finally {
    await context.dispose();
  }
}

/** Upload and expect 201 `queued`. */
export async function mustUpload(
  api: ApiSession,
  loc: Loc,
  name: string,
  body: Buffer,
): Promise<DocumentItem> {
  const result = await uploadRaw(api, loc, name, body);
  expect(result.status, `${name}: ${result.text}`).toBe(201);
  return json<DocumentItem>(result);
}

export async function listDocs(
  api: ApiSession,
  ws: string,
  col: string,
  folderId?: string,
): Promise<DocumentItem[]> {
  const query = folderId ? `?folder_id=${folderId}` : "";
  const result = await api.send("GET", `${docsPath(ws, col)}${query}`);
  expect(result.status, result.text).toBe(200);
  return json<{ documents: DocumentItem[] }>(result).documents;
}

export async function getDoc(
  api: ApiSession,
  ws: string,
  col: string,
  id: string,
): Promise<DocumentItem | undefined> {
  return (await listDocs(api, ws, col)).find((item) => item.id === id);
}

/** Polls the list until the document reaches one of `statuses`; returns it. */
export async function waitStatus(
  api: ApiSession,
  ws: string,
  col: string,
  id: string,
  statuses: DocStatus[] = TERMINAL,
  timeoutMs = 120_000,
): Promise<DocumentItem> {
  const deadline = Date.now() + timeoutMs;
  let last: DocumentItem | undefined;
  while (Date.now() < deadline) {
    last = await getDoc(api, ws, col, id);
    if (last && statuses.includes(last.status)) return last;
    await sleep(500);
  }
  throw new Error(
    `document ${id} did not reach ${statuses.join("/")}: last ${JSON.stringify(last)}`,
  );
}

export async function mustReady(
  api: ApiSession,
  loc: Loc,
  name: string,
  body: Buffer,
): Promise<DocumentItem> {
  const queued = await mustUpload(api, loc, name, body);
  const done = await waitStatus(api, loc.ws, loc.col, queued.id);
  expect(done.status, `${name}: ${JSON.stringify(done)}`).toBe("ready");
  return done;
}

export function textPath(ws: string, col: string, id: string): string {
  return `${docsPath(ws, col)}/${id}/text`;
}
export function chunksPath(ws: string, col: string, id: string): string {
  return `${docsPath(ws, col)}/${id}/chunks`;
}

export async function chunksOf(
  api: ApiSession,
  ws: string,
  col: string,
  id: string,
): Promise<Chunk[]> {
  const result = await api.send("GET", chunksPath(ws, col, id));
  expect(result.status, result.text).toBe(200);
  return json<{ chunks: Chunk[] }>(result).chunks;
}

export async function textOf(
  api: ApiSession,
  ws: string,
  col: string,
  id: string,
): Promise<TextBody> {
  const result = await api.send("GET", textPath(ws, col, id));
  expect(result.status, result.text).toBe(200);
  return json<TextBody>(result);
}

export async function deleteDoc(
  api: ApiSession,
  ws: string,
  col: string,
  id: string,
): Promise<ApiResult> {
  return api.send("DELETE", `${docsPath(ws, col)}/${id}`);
}

// ---------------------------------------------------------------------------------------------
// Raw socket request: lets a test state a Content-Length that does not match the body
// ---------------------------------------------------------------------------------------------

export type RawResult = { status: number; text: string; json: unknown; ms: number };

/**
 * POST to the API port directly with a stated Content-Length and only `body` as payload. Resolves as
 * soon as the response head and a short grace period of the body arrived (the server may close early).
 */
export function rawUpload(options: {
  loc: Loc;
  api: ApiSession;
  name: string;
  contentLength: number;
  body?: Buffer;
}): Promise<RawResult> {
  const { loc, api, name, contentLength } = options;
  const cookie = [...api.jar].map(([key, value]) => `${key}=${value}`).join("; ");
  const csrf = api.jar.get("ei_csrf") ?? "";
  const head =
    `POST ${uploadPath(loc).replace(/^\/api/, "")} HTTP/1.1\r\nHost: ${API_DIRECT.host}:${API_DIRECT.port}\r\n` +
    `Cookie: ${cookie}\r\nX-CSRF-Token: ${csrf}\r\nOrigin: ${ADMIN_ORIGIN}\r\n` +
    `X-File-Name: ${encodeURIComponent(name)}\r\nContent-Type: application/octet-stream\r\n` +
    `Content-Length: ${contentLength}\r\nConnection: close\r\n\r\n`;
  return new Promise((resolve) => {
    const started = Date.now();
    let received = "";
    let settled = false;
    const finish = (): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.destroy();
      const match = /^HTTP\/1\.[01] (\d{3})/.exec(received);
      if (!match) {
        // The server kept waiting for the rest of the announced body: no response at all.
        resolve({ status: 0, text: received, json: null, ms: Date.now() - started });
        return;
      }
      const bodyText = received.slice(received.indexOf("\r\n\r\n") + 4);
      const open = bodyText.indexOf("{");
      const close = bodyText.lastIndexOf("}");
      let parsed: unknown = null;
      if (open >= 0 && close > open) {
        try {
          parsed = JSON.parse(bodyText.slice(open, close + 1));
        } catch {
          parsed = null;
        }
      }
      resolve({ status: Number(match[1]), text: bodyText, json: parsed, ms: Date.now() - started });
    };
    const timer = setTimeout(finish, 15_000);
    const socket = net.connect(API_DIRECT, () => {
      socket.write(head);
      if (options.body) socket.write(options.body);
    });
    socket.on("data", (data: Buffer) => {
      received += data.toString("latin1");
      if (received.includes("\r\n\r\n")) setTimeout(finish, 300);
    });
    socket.on("error", () => finish());
    socket.on("close", () => finish());
  });
}

// ---------------------------------------------------------------------------------------------
// Database and storage checks as the superuser
// ---------------------------------------------------------------------------------------------

export type Counts = {
  documents: number;
  chunks: number;
  folders: number;
  collections: number;
  audit: number;
};

export function counts(): Counts {
  return {
    documents: Number(sql("select count(*) from documents")),
    chunks: Number(sql("select count(*) from document_chunks")),
    folders: Number(sql("select count(*) from folders")),
    collections: Number(sql("select count(*) from collections")),
    audit: Number(
      sql(
        "select count(*) from audit_events where action like 'document.%' or action like 'folder.%' or action like 'collection.%'",
      ),
    ),
  };
}

/** Rows of documents, chunks, folders and collections that still carry the marker (must be empty). */
export function markerRows(): string[] {
  const like = "'%qa-ea33-%'";
  return rows(
    `select 'document' from documents d where to_jsonb(d)::text ilike ${like}
     union all select 'chunk' from document_chunks c where to_jsonb(c)::text ilike ${like}
     union all select 'folder' from folders f where to_jsonb(f)::text ilike ${like}
     union all select 'collection' from collections c2 where to_jsonb(c2)::text ilike ${like}`,
  );
}

/** Audit rows whose text contains `value` (file names and document text must never appear). */
export function auditRowsContaining(value: string): number {
  const safe = value.replace(/'/g, "''");
  return Number(
    sql(`select count(*) from audit_events a where to_jsonb(a)::text ilike '%${safe}%'`),
  );
}

export function chunkRows(documentId: string): number {
  return Number(sql(`select count(*) from document_chunks where document_id = '${documentId}'`));
}
export function documentRows(documentId: string): number {
  return Number(sql(`select count(*) from documents where id = '${documentId}'`));
}
export function orgOfDocument(documentId: string): string {
  return sql(`select org_id from documents where id = '${documentId}'`);
}

export type AuditRow = {
  action: string;
  target_type: string;
  old_value: string | null;
  new_value: string | null;
  actor: string;
};

export function auditOf(targetId: string): AuditRow[] {
  const out = sql(
    `select coalesce(json_agg(t order by t.created_at), '[]'::json) from (
       select action, target_type, old_value, new_value, actor, created_at
       from audit_events where target_id::text = '${targetId}') t`,
  );
  return (JSON.parse(out) as (AuditRow & { created_at: string })[]).map((row) => ({
    action: row.action,
    target_type: row.target_type,
    old_value: row.old_value,
    new_value: row.new_value,
    actor: row.actor,
  }));
}

const fileIds = new Map<string, string>();

/** `documents.file_id` (superuser SQL; never in an API response). Remembered, so it survives the delete. */
export function fileIdOf(documentId: string): string | undefined {
  const known = fileIds.get(documentId);
  if (known) return known;
  const found = sql(`select file_id from documents where id = '${documentId}'`).trim();
  if (found) fileIds.set(documentId, found);
  return found || undefined;
}

/** 1 when `/var/lib/ei-ai/files/<org>/<file_id>.bin` exists in the api container, else 0. */
export function storedFiles(orgId: string, documentId: string): number {
  const fileId = fileIdOf(documentId);
  if (!fileId) return 0;
  const run = compose([
    "exec",
    "-T",
    "api",
    "sh",
    "-c",
    `if [ -f /var/lib/ei-ai/files/${orgId}/${fileId}.bin ]; then echo 1; else echo 0; fi`,
  ]);
  return Number(run.stdout.trim());
}

/** Size and first 4 bytes (hex) of the stored original, or null when absent. */
export function storedHeader(
  orgId: string,
  documentId: string,
): { size: number; head: string } | null {
  const fileId = fileIdOf(documentId);
  if (!fileId) return null;
  const path = `/var/lib/ei-ai/files/${orgId}/${fileId}.bin`;
  const run = compose([
    "exec",
    "-T",
    "api",
    "sh",
    "-c",
    `[ -f ${path} ] && echo "$(wc -c < ${path}) $(head -c 4 ${path} | od -An -tx1 | tr -d ' ')"`,
  ]);
  const [size, head] = run.stdout.trim().split(" ");
  return size ? { size: Number(size), head: head ?? "" } : null;
}

/** Number of files under the storage root containing `needle` (grep -rl; must be 0 for plaintext). */
export function plaintextHits(needle: string): number {
  const run = compose([
    "exec",
    "-T",
    "api",
    "sh",
    "-c",
    `grep -rl -- '${needle}' /var/lib/ei-ai/files | wc -l`,
  ]);
  return Number(run.stdout.trim());
}

/** Waits until the stored original of a document is gone (the contract: within seconds / 60 s). */
export async function waitStoredGone(
  orgId: string,
  documentId: string,
  timeoutMs = 60_000,
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (storedFiles(orgId, documentId) <= 0) return true;
    await sleep(1000);
  }
  return false;
}

/** Everything the API container logged so far (text and file names must not be in it). */
export function logsOfApi(): string {
  return compose(["logs", "--no-color", "api"]).stdout;
}

export function sha256(buffer: Buffer): string {
  return createHash("sha256").update(buffer).digest("hex");
}

/** Removes everything this run created (API first, as the creators; SQL fallback; temp files). */
export async function cleanupAll(): Promise<void> {
  for (const [id, creator] of [...trackedDocs]) {
    try {
      await deleteDoc(creator.api, creator.ws, creator.col, id);
    } catch {
      // the SQL fallback below removes what is left
    }
  }
  trackedDocs.clear();
  for (const folder of [...trackedFolders].reverse()) {
    try {
      await folder.api.send(
        "DELETE",
        `${collectionsPath(folder.ws)}/${folder.col}/folders/${folder.id}`,
      );
    } catch {
      // folder removal is retried through SQL
    }
  }
  for (const [id, owner] of trackedCollections) {
    try {
      await owner.api.send("DELETE", `${collectionsPath(owner.ws)}/${id}`);
    } catch {
      // SQL fallback
    }
  }
  // Documents uploaded through the browser are not tracked: find them by the marker, remove them through
  // the API as the Workspace Admin (this also removes the stored original), remember their ids.
  const untracked = rows(
    `select d.id || ' ' || c.workspace_id || ' ' || c.id from documents d
       join folders f on f.id = d.folder_id join collections c on c.id = f.collection_id
       where to_jsonb(d)::text ilike '%qa-ea33-%'`,
  );
  if (untracked.length > 0) {
    const admin = await apiOf("linh");
    for (const line of untracked) {
      const [id, workspaceId, collectionId] = line.split(" ");
      if (!id || !workspaceId || !collectionId) continue;
      everDocIds.add(id);
      try {
        await deleteDoc(admin, workspaceId, collectionId, id);
      } catch {
        // the SQL fallback below removes what is left
      }
    }
  }
  const ids = createdIds();
  const quoted = ids.map((id) => `'${id}'`).join(", ");
  const like = "'%qa-ea33-%'";
  const orphans = `select id from documents d where to_jsonb(d)::text ilike ${like}${
    ids.length > 0 ? ` or id::text in (${quoted})` : ""
  }`;
  const statements = [
    `delete from document_chunks where document_id in (${orphans})`,
    `delete from documents where id in (${orphans})`,
  ];
  if (ids.length > 0) {
    statements.push(`delete from audit_events where target_id::text in (${quoted})`);
  }
  // Documents uploaded and removed through the browser are unknown to the run: their audit rows are the
  // document events written since this process started whose document no longer exists.
  statements.push(
    `delete from audit_events where action like 'document.%' and created_at >= '${RUN_STARTED}' and target_id::text not in (select id::text from documents)`,
    `delete from audit_events a where (action like 'folder.%' or action like 'collection.%') and to_jsonb(a)::text ilike ${like}`,
    `delete from folders f where to_jsonb(f)::text ilike ${like}`,
    `delete from collections c where to_jsonb(c)::text ilike ${like}`,
  );
  for (const statement of statements) {
    try {
      sql(statement);
    } catch (error) {
      // best effort: the hygiene check in afterAll proves the result
      console.warn(`cleanup statement failed: ${statement.slice(0, 80)} ${String(error)}`);
    }
  }
  trackedFolders.length = 0;
  trackedCollections.clear();
  fs.rmSync(TMP_DIR, { recursive: true, force: true });
}

export const ORG = DEMO_ORG;

// ---------------------------------------------------------------------------------------------
// Test text
// ---------------------------------------------------------------------------------------------

const SENTENCE =
  "Employees record the worked hours in the timesheet and the manager approves them before the deadline. ";

/** About `chars` characters of plain English, every sentence carrying the marker word. */
export function filler(marker: string, chars: number): string {
  let out = "";
  while (out.length < chars) out += SENTENCE.replace("Employees", `Employees ${marker}`);
  return out.trim();
}

const VI_SENTENCE =
  "Nhân viên ghi nhận giờ làm thêm trong bảng chấm công và quản lý phê duyệt trước hạn chót. ";

/** About `chars` characters of Vietnamese (NFC), every sentence carrying the marker word. */
export function fillerVi(marker: string, chars: number): string {
  let out = "";
  while (out.length < chars) out += VI_SENTENCE.replace("Nhân viên", `Nhân viên ${marker}`);
  return out.trim();
}

/** A text of exactly `length` ASCII characters that starts and ends with a letter. */
export function exactText(length: number): string {
  const word = "abcd ";
  const body = word.repeat(Math.ceil(length / word.length)).slice(0, length);
  return body.endsWith(" ") ? `${body.slice(0, -1)}e` : body;
}

// ---------------------------------------------------------------------------------------------
// Document structure shared by the MD and DOCX builders
// ---------------------------------------------------------------------------------------------

export type Section = {
  /** Heading level 1-3, or 0 for text before the first heading. */
  level: 0 | 1 | 2 | 3;
  title: string;
  marker: string;
  chars: number;
  /** Heading titles from the outermost one down to this section (what heading_path must hold). */
  path: string[];
};

/** The "Overtime Policy 2026" document: a preamble, H1, H2, two H3 (3.2 is long: several chunks). */
export const OVERTIME: Section[] = [
  { level: 0, title: "", marker: "zqmpre", chars: 500, path: [] },
  {
    level: 1,
    title: "Overtime Policy 2026",
    marker: "zqmroot",
    chars: 700,
    path: ["Overtime Policy 2026"],
  },
  {
    level: 2,
    title: "1. Scope",
    marker: "zqmscope",
    chars: 1200,
    path: ["Overtime Policy 2026", "1. Scope"],
  },
  {
    level: 2,
    title: "3. Approvals",
    marker: "zqmappr",
    chars: 800,
    path: ["Overtime Policy 2026", "3. Approvals"],
  },
  {
    level: 3,
    title: "3.1 Weekday work",
    marker: "zqmweekday",
    chars: 1100,
    path: ["Overtime Policy 2026", "3. Approvals", "3.1 Weekday work"],
  },
  {
    level: 3,
    title: "3.2 Weekend work",
    marker: "zqmweekend",
    chars: 5200,
    path: ["Overtime Policy 2026", "3. Approvals", "3.2 Weekend work"],
  },
];

/** The same structure in Vietnamese; headings carry combining-capable diacritics. */
export const OVERTIME_VI: Section[] = [
  { level: 0, title: "", marker: "zqmpre", chars: 400, path: [] },
  {
    level: 1,
    title: "Quy định làm thêm giờ 2026",
    marker: "zqmroot",
    chars: 600,
    path: ["Quy định làm thêm giờ 2026"],
  },
  {
    level: 2,
    title: "1. Phạm vi áp dụng",
    marker: "zqmscope",
    chars: 1000,
    path: ["Quy định làm thêm giờ 2026", "1. Phạm vi áp dụng"],
  },
  {
    level: 2,
    title: "3. Phê duyệt",
    marker: "zqmappr",
    chars: 700,
    path: ["Quy định làm thêm giờ 2026", "3. Phê duyệt"],
  },
  {
    level: 3,
    title: "3.2 Làm thêm cuối tuần",
    marker: "zqmweekend",
    chars: 4200,
    path: ["Quy định làm thêm giờ 2026", "3. Phê duyệt", "3.2 Làm thêm cuối tuần"],
  },
];

/** Markdown for a structure; `vi` selects the Vietnamese filler. */
export function buildMd(sections: Section[], vi = false): string {
  const make = vi ? fillerVi : filler;
  return (
    sections
      .map((section) => {
        const heading =
          section.level > 0 ? `${"#".repeat(section.level)} ${section.title}\n\n` : "";
        return `${heading}${make(section.marker, section.chars)}\n`;
      })
      .join("\n") + "\n"
  );
}

export function normalise(text: string, form: "NFC" | "NFD"): string {
  return text.normalize(form);
}

// ---------------------------------------------------------------------------------------------
// ZIP and DOCX writers
// ---------------------------------------------------------------------------------------------

const CRC_TABLE = ((): Uint32Array => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

export function crc32(buffer: Buffer): number {
  let crc = 0xffffffff;
  for (const byte of buffer) crc = (CRC_TABLE[(crc ^ byte) & 0xff] ?? 0) ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

export type ZipEntry = { name: string; data: Buffer; deflate?: boolean };

/** A ZIP archive (stored or deflated entries, ASCII names, no ZIP64). */
export function buildZip(entries: ZipEntry[]): Buffer {
  const parts: Buffer[] = [];
  const central: Buffer[] = [];
  let offset = 0;
  for (const entry of entries) {
    const name = Buffer.from(entry.name, "latin1");
    const packed = entry.deflate ? deflateRawSync(entry.data) : entry.data;
    const method = entry.deflate ? 8 : 0;
    const crc = crc32(entry.data);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0, 6);
    local.writeUInt16LE(method, 8);
    local.writeUInt16LE(0, 10);
    local.writeUInt16LE(0x21, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(packed.length, 18);
    local.writeUInt32LE(entry.data.length, 22);
    local.writeUInt16LE(name.length, 26);
    local.writeUInt16LE(0, 28);
    parts.push(local, name, packed);
    const header = Buffer.alloc(46);
    header.writeUInt32LE(0x02014b50, 0);
    header.writeUInt16LE(20, 4);
    header.writeUInt16LE(20, 6);
    header.writeUInt16LE(0, 8);
    header.writeUInt16LE(method, 10);
    header.writeUInt16LE(0, 12);
    header.writeUInt16LE(0x21, 14);
    header.writeUInt32LE(crc, 16);
    header.writeUInt32LE(packed.length, 20);
    header.writeUInt32LE(entry.data.length, 24);
    header.writeUInt16LE(name.length, 28);
    header.writeUInt32LE(offset, 42);
    central.push(header, name);
    offset += local.length + name.length + packed.length;
  }
  const directory = Buffer.concat(central);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(directory.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...parts, directory, end]);
}

function xmlEscape(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

const W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';

const DOCX_STYLES = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles ${W_NS}>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>
</w:styles>`;

const CONTENT_TYPES = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>`;

const ROOT_RELS = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>`;

/** A .docx with Heading1-3 styles. `pages` goes into docProps/app.xml (the stored page count). */
export function buildDocxFromXml(bodyXml: string, pages?: number): Buffer {
  const entries: ZipEntry[] = [
    { name: "[Content_Types].xml", data: Buffer.from(CONTENT_TYPES) },
    { name: "_rels/.rels", data: Buffer.from(ROOT_RELS) },
    {
      name: "word/_rels/document.xml.rels",
      data: Buffer.from(
        `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>`,
      ),
    },
    { name: "word/styles.xml", data: Buffer.from(DOCX_STYLES) },
    {
      name: "word/document.xml",
      data: Buffer.from(
        `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document ${W_NS}><w:body>${bodyXml}</w:body></w:document>`,
      ),
      deflate: true,
    },
    {
      name: "docProps/app.xml",
      data: Buffer.from(
        `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>Microsoft Office Word</Application>${
          pages === undefined ? "" : `<Pages>${pages}</Pages>`
        }</Properties>`,
      ),
    },
  ];
  return buildZip(entries);
}

function paragraphXml(text: string, style?: string): string {
  const props = style ? `<w:pPr><w:pStyle w:val="${style}"/></w:pPr>` : "";
  return `<w:p>${props}<w:r><w:t xml:space="preserve">${xmlEscape(text)}</w:t></w:r></w:p>`;
}

/** DOCX for a structure (headings as Heading1-3). */
export function buildDocx(
  sections: Section[],
  options: { vi?: boolean; pages?: number; form?: "NFC" | "NFD" } = {},
): Buffer {
  const make = options.vi ? fillerVi : filler;
  const form = (text: string): string => (options.form ? text.normalize(options.form) : text);
  const xml = sections
    .map((section) => {
      const heading =
        section.level > 0 ? paragraphXml(form(section.title), `Heading${section.level}`) : "";
      return heading + paragraphXml(form(make(section.marker, section.chars)));
    })
    .join("");
  return buildDocxFromXml(xml, options.pages);
}

/** A DOCX with no text at all. */
export function buildEmptyDocx(): Buffer {
  return buildDocxFromXml("<w:p/>");
}

/** A small file that expands to more than 250 MB when unzipped (word/document.xml). */
export function buildZipBombDocx(expandedMb = 300): Buffer {
  const head = Buffer.from(`<w:document ${W_NS}><w:body><w:p><w:r><w:t>`);
  const tail = Buffer.from("</w:t></w:r></w:p></w:body></w:document>");
  const big = Buffer.alloc(expandedMb * MB, 0x41);
  return buildZip([
    { name: "[Content_Types].xml", data: Buffer.from(CONTENT_TYPES) },
    { name: "_rels/.rels", data: Buffer.from(ROOT_RELS) },
    { name: "word/document.xml", data: Buffer.concat([head, big, tail]), deflate: true },
  ]);
}

// ---------------------------------------------------------------------------------------------
// PDF writers (Helvetica, ASCII text)
// ---------------------------------------------------------------------------------------------

function pdfFile(objects: Buffer[], trailerExtra = ""): Buffer {
  const header = Buffer.from("%PDF-1.4\n%\xe2\xe3\xcf\xd3\n", "latin1");
  const parts: Buffer[] = [header];
  const offsets: number[] = [];
  let position = header.length;
  objects.forEach((body, index) => {
    offsets.push(position);
    const piece = Buffer.concat([
      Buffer.from(`${index + 1} 0 obj\n`, "latin1"),
      body,
      Buffer.from("\nendobj\n", "latin1"),
    ]);
    parts.push(piece);
    position += piece.length;
  });
  const xref =
    `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n` +
    offsets.map((value) => `${String(value).padStart(10, "0")} 00000 n \n`).join("");
  parts.push(
    Buffer.from(
      `${xref}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R${trailerExtra} >>\nstartxref\n${position}\n%%EOF\n`,
      "latin1",
    ),
  );
  return Buffer.concat(parts);
}

function streamObject(dict: string, data: Buffer): Buffer {
  return Buffer.concat([
    Buffer.from(`<< ${dict} /Length ${data.length} >>\nstream\n`, "latin1"),
    data,
    Buffer.from("\nendstream", "latin1"),
  ]);
}

function wrapWords(text: string, width: number): string[] {
  const lines: string[] = [];
  let line = "";
  for (const word of text.split(/\s+/)) {
    if (line.length + word.length + 1 > width && line.length > 0) {
      lines.push(line);
      line = word;
    } else {
      line = line.length > 0 ? `${line} ${word}` : word;
    }
  }
  if (line.length > 0) lines.push(line);
  return lines;
}

function pdfEscape(text: string): string {
  return text.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
}

function pageContent(text: string): Buffer {
  if (text.trim() === "") return Buffer.from("", "latin1");
  const lines = wrapWords(text, 100);
  const body = lines.map((line) => `(${pdfEscape(line)}) Tj 0 -11 Td`).join("\n");
  return Buffer.from(`BT /F1 9 Tf 40 800 Td\n${body}\nET`, "latin1");
}

/** A PDF with a real text layer: one page per string (an empty string gives a blank page). */
export function buildPdf(pages: string[], trailerExtra = "", encrypt?: Buffer): Buffer {
  const objects: Buffer[] = [];
  const kids = pages.map((_, index) => `${4 + index * 2} 0 R`).join(" ");
  objects.push(Buffer.from("<< /Type /Catalog /Pages 2 0 R >>", "latin1"));
  objects.push(Buffer.from(`<< /Type /Pages /Kids [${kids}] /Count ${pages.length} >>`, "latin1"));
  objects.push(Buffer.from("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", "latin1"));
  pages.forEach((text, index) => {
    objects.push(
      Buffer.from(
        `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents ${5 + index * 2} 0 R >>`,
        "latin1",
      ),
    );
    objects.push(streamObject("", pageContent(text)));
  });
  if (encrypt) objects.push(encrypt);
  return pdfFile(objects, trailerExtra);
}

/** A PDF whose pages hold only an image (no text layer), like a scan. */
export function buildScannedPdf(pageCount: number): Buffer {
  const objects: Buffer[] = [];
  const kids = Array.from({ length: pageCount }, (_, index) => `${4 + index * 2} 0 R`).join(" ");
  objects.push(Buffer.from("<< /Type /Catalog /Pages 2 0 R >>", "latin1"));
  objects.push(Buffer.from(`<< /Type /Pages /Kids [${kids}] /Count ${pageCount} >>`, "latin1"));
  const pixels = Buffer.alloc(64 * 64);
  for (let index = 0; index < pixels.length; index++) pixels[index] = (index * 7) % 256;
  objects.push(
    streamObject(
      "/Type /XObject /Subtype /Image /Width 64 /Height 64 /ColorSpace /DeviceGray /BitsPerComponent 8",
      pixels,
    ),
  );
  const imageId = 3;
  for (let index = 0; index < pageCount; index++) {
    objects.push(
      Buffer.from(
        `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /XObject << /Im1 ${imageId} 0 R >> >> /Contents ${5 + index * 2} 0 R >>`,
        "latin1",
      ),
    );
    objects.push(streamObject("", Buffer.from("q 595 0 0 842 0 0 cm /Im1 Do Q", "latin1")));
  }
  return pdfFile(objects);
}

const PDF_PAD = Buffer.from(
  "28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A",
  "hex",
);

function rc4(key: Buffer, data: Buffer): Buffer {
  const state = Array.from({ length: 256 }, (_, index) => index);
  let j = 0;
  for (let i = 0; i < 256; i++) {
    j = (j + (state[i] ?? 0) + (key[i % key.length] ?? 0)) & 255;
    [state[i], state[j]] = [state[j] ?? 0, state[i] ?? 0];
  }
  const out = Buffer.alloc(data.length);
  let a = 0;
  let b = 0;
  for (let n = 0; n < data.length; n++) {
    a = (a + 1) & 255;
    b = (b + (state[a] ?? 0)) & 255;
    [state[a], state[b]] = [state[b] ?? 0, state[a] ?? 0];
    out[n] = (data[n] ?? 0) ^ (state[((state[a] ?? 0) + (state[b] ?? 0)) & 255] ?? 0);
  }
  return out;
}

function padPassword(password: string): Buffer {
  return Buffer.concat([Buffer.from(password, "latin1"), PDF_PAD]).subarray(0, 32);
}

/**
 * A PDF protected with a user password (standard security handler, revision 2, RC4 40 bit) that is not
 * empty, so a reader cannot open it without the password. The page text stays in the clear: only the
 * password check matters for the "password_protected" case.
 */
export function buildPasswordPdf(userPassword = "qa-secret"): Buffer {
  const id = randomBytes(16);
  const ownerKey = createHash("md5").update(padPassword("qa-owner")).digest().subarray(0, 5);
  const owner = rc4(ownerKey, padPassword(userPassword));
  const permissions = Buffer.alloc(4);
  permissions.writeInt32LE(-4, 0);
  const key = createHash("md5")
    .update(Buffer.concat([padPassword(userPassword), owner, permissions, id]))
    .digest()
    .subarray(0, 5);
  const user = rc4(key, PDF_PAD);
  const dict = Buffer.from(
    `<< /Filter /Standard /V 1 /R 2 /O <${owner.toString("hex")}> /U <${user.toString("hex")}> /P -4 >>`,
    "latin1",
  );
  const pages = [filler("zqpw", 600)];
  const encryptId = 4 + pages.length * 2;
  return buildPdf(
    pages,
    ` /Encrypt ${encryptId} 0 R /ID [<${id.toString("hex")}> <${id.toString("hex")}>]`,
    dict,
  );
}

/** Random bytes: not any supported format. */
export function randomJunk(size = 2048): Buffer {
  return randomBytes(size);
}

// ---------------------------------------------------------------------------------------------
// Chunk invariants (AC5, AC6)
// ---------------------------------------------------------------------------------------------

/**
 * Checks what the contract promises for every chunk list: ordinals 0..n-1, `text` equals the slice of the
 * extracted text, sizes about 300-500 tokens (loose bounds), overlap between consecutive chunks of the
 * same page or section, and the exact set of keys.
 */
export function expectChunkInvariants(chunks: Chunk[], extracted: string): void {
  expect(chunks.length, "at least one chunk").toBeGreaterThan(0);
  chunks.forEach((chunk, index) => {
    expect(Object.keys(chunk).sort(), `chunk ${index} keys`).toEqual(CHUNK_KEYS);
    expect(chunk.ordinal, "ordinal").toBe(index);
    // The text route returns at most 100 000 characters: later chunks cannot be compared with it.
    if (chunk.char_end <= extracted.length) {
      expect(chunk.text, `chunk ${index} text equals extracted[char_start:char_end]`).toBe(
        extracted.slice(chunk.char_start, chunk.char_end),
      );
    }
    expect(chunk.char_end, "char_end after char_start").toBeGreaterThan(chunk.char_start);
    expect(
      Math.abs(chunk.token_estimate - chunk.text.length / 4),
      "token_estimate = chars / 4",
    ).toBeLessThanOrEqual(2);
    expect(chunk.token_estimate, `chunk ${index} size (tokens)`).toBeLessThanOrEqual(560);
  });
  const sameUnit = (a: Chunk, b: Chunk): boolean =>
    a.page === b.page && JSON.stringify(a.heading_path) === JSON.stringify(b.heading_path);
  for (let index = 1; index < chunks.length; index++) {
    const previous = chunks[index - 1] as Chunk;
    const current = chunks[index] as Chunk;
    if (!sameUnit(previous, current)) continue;
    const overlap = previous.char_end - current.char_start;
    expect(overlap, `overlap of chunk ${index - 1} and ${index} (chars)`).toBeGreaterThanOrEqual(
      80,
    );
    expect(overlap, `overlap of chunk ${index - 1} and ${index} (chars)`).toBeLessThanOrEqual(400);
    expect(
      previous.token_estimate,
      `full-size chunk ${index - 1} before an overlapping one`,
    ).toBeGreaterThanOrEqual(240);
  }
}

/** Marker words (zq...) found in a text. */
export function markersIn(text: string): string[] {
  return [...new Set(text.match(/zq[a-z0-9]+/g) ?? [])];
}

/** Every chunk holds markers of one section only and carries that section's heading path. */
export function expectSectionsRespected(chunks: Chunk[], sections: Section[]): void {
  const byMarker = new Map(sections.map((section) => [section.marker, section]));
  for (const chunk of chunks) {
    const markers = markersIn(chunk.text);
    expect(
      markers.length,
      `a chunk never spans two sections: ${markers.join(",")}`,
    ).toBeLessThanOrEqual(1);
    const marker = markers[0];
    if (marker === undefined) continue;
    expect(chunk.heading_path, `heading path of a chunk of ${marker}`).toEqual(
      byMarker.get(marker)?.path,
    );
    expect(chunk.page, "no page for DOCX/MD").toBeNull();
  }
  for (const section of sections) {
    const own = chunks.filter((chunk) => markersIn(chunk.text).includes(section.marker));
    expect(own.length, `section ${section.marker} has chunks`).toBeGreaterThan(0);
  }
}

// ---------------------------------------------------------------------------------------------
// Browser helpers
// ---------------------------------------------------------------------------------------------

let tempCounter = 0;

/** Writes a test file under .work/EA-33/tmp/<run>/<n>/<name> (the exact name, for setInputFiles). */
export function tempFile(name: string, bytes: Buffer | string): string {
  const dir = path.join(TMP_DIR, String(tempCounter++));
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, name);
  fs.writeFileSync(file, bytes);
  return file;
}

/** A sparse file of exactly `size` bytes (zeros), for the size limit checks. */
export function tempFileOfSize(name: string, size: number): string {
  const dir = path.join(TMP_DIR, String(tempCounter++));
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, name);
  const handle = fs.openSync(file, "w");
  fs.ftruncateSync(handle, size);
  fs.closeSync(handle);
  return file;
}

export async function openCollectionPage(page: Page, ws: string, col: string): Promise<void> {
  await page.goto(`/w/${ws}/knowledge/${col}`);
  await expect(page.getByTestId("collection-detail")).toBeVisible();
  await expect(page.getByTestId("folders-panel")).toBeVisible();
}

/** The folder row whose select button starts with the folder name. */
export function folderRowOf(page: Page, name: string): Locator {
  return page.getByTestId("folder-row").filter({
    has: page
      .getByTestId("folder-select")
      .filter({ hasText: new RegExp(`^\\s*${escapeRegExp(name)}`) }),
  });
}

export async function selectFolder(page: Page, name: string): Promise<void> {
  const button = folderRowOf(page, name).getByTestId("folder-select");
  await button.click();
  await expect(button).toHaveAttribute("aria-current", "true");
}

export async function selectAllDocuments(page: Page): Promise<void> {
  const entry = page.getByTestId("all-documents");
  await entry.click();
  await expect(entry).toHaveAttribute("aria-current", "true");
}

/** The table row of a document by its exact file name. */
export function docRow(page: Page, name: string): Locator {
  return page.getByTestId("document-row").filter({
    has: page
      .getByTestId("document-name")
      .filter({ hasText: new RegExp(`^\\s*${escapeRegExp(name)}\\s*$`) }),
  });
}

export function folderCount(page: Page, name: string): Locator {
  return folderRowOf(page, name).getByTestId("folder-count");
}

/** Chooses files through the hidden input of the drop zone (paths from tempFile). */
export async function chooseFiles(page: Page, files: string[]): Promise<void> {
  await page.getByTestId("file-input").setInputFiles(files);
}

/** Texts of the rejection lines, in screen order. */
export async function rejectionLines(page: Page): Promise<string[]> {
  const all = await page.getByTestId("upload-rejection").allTextContents();
  return all.map((text) => text.replace(/\s+/g, " ").trim());
}

/** Every POST of the page to the upload route, as { path, name } (name from X-File-Name). */
export function uploadRequests(page: Page): { path: string; name: string | null }[] {
  const seen: { path: string; name: string | null }[] = [];
  page.on("request", (request) => {
    const { pathname } = new URL(request.url());
    if (request.method() === "POST" && /\/documents$/.test(pathname)) {
      const header = request.headers()["x-file-name"];
      seen.push({ path: pathname, name: header === undefined ? null : decodeURIComponent(header) });
    }
  });
  return seen;
}

/** Waits until a table row reaches the status text; the page refreshes itself (no reload). */
export async function expectStatusText(
  row: Locator,
  text: string | RegExp,
  timeout = 90_000,
): Promise<void> {
  await expect(row.getByTestId("document-status")).toHaveText(text, { timeout });
}

export const ready = (pages: number): string =>
  `Ready · ${pages} ${pages === 1 ? "page" : "pages"}`;
