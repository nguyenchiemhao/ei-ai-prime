// EA-35 (KB-04): helpers of the vector index specs. Black-box only: the admin origin (UI + /api proxy), the
// operator CLI `ei-ai index ...` through `docker compose exec`, psql as the database superuser and the
// container logs. Builds on ./ea22, ./ea32, ./ea33 and ./ea94 (seeded accounts, upload helpers, test files).
// Everything a run creates carries the marker `qa-EA35-<run>` (folder, collection and file names), so
// cleanupAll() and markerRows() can find it. Seed rows are never changed.
//
// Draft location: .work/EA-35/e2e-draft/support/ea35.ts; the `run` mode moves it to e2e/support/ea35.ts.
import { expect } from "@playwright/test";
import {
  ADMIN,
  DEMO_ORG,
  RUN,
  UUID,
  compose,
  lines,
  peopleOpsId,
  rows,
  sleep,
  sql,
  type ApiSession,
  type Run,
} from "./ea22";
import { collectionsPath, json, type CollectionItem, type FolderItem } from "./ea32";
import {
  SONGHAN_ORG,
  apiOf,
  deleteDoc,
  getDoc,
  uploadRaw,
  waitStatus,
  type DocumentItem,
  type Loc,
} from "./ea33";

export { DEMO_ORG, RUN, SONGHAN_ORG, UUID };
export const MARK = `qa-EA35-${RUN}`;
export const MODEL_REF = "bge-m3@2026.10";
export const MODEL_ID = "bge-m3";
export const MODEL_VERSION = "2026.10";
/** Deadline of AC1 from Ready, with a margin for the polling interval. */
export const INDEX_DEADLINE_MS = 120_000;
export const POLL_MS = 2000;

export type AccessLevel = "public" | "authenticated" | "restricted";

// ---------------------------------------------------------------------------------------------
// Tracked writes: everything created is deleted again by cleanupAll()
// ---------------------------------------------------------------------------------------------

type DocOwner = { api: ApiSession; ws: string; col: string };
const trackedDocs = new Map<string, DocOwner>();
const trackedFolders: { id: string; api: ApiSession; ws: string; col: string }[] = [];
const trackedCollections = new Map<string, { api: ApiSession; ws: string }>();
const RUN_STARTED = new Date(Date.now() - 5000).toISOString();

export function trackDoc(id: string, owner: DocOwner): void {
  trackedDocs.set(id, owner);
}

/** Creates a folder `<MARK>-<label>` and registers it for cleanup. */
export async function makeFolder(
  api: ApiSession,
  ws: string,
  col: string,
  label: string,
): Promise<FolderItem> {
  const result = await api.send("POST", `${collectionsPath(ws)}/${col}/folders`, {
    json: { name: `${MARK}-${label}` },
  });
  expect(result.status, result.text).toBe(201);
  const folder = json<FolderItem>(result);
  trackedFolders.push({ id: folder.id, api, ws, col });
  return folder;
}

/** Creates a collection `<MARK>-<label>` with the given access and registers it for cleanup. */
export async function makeCollection(
  api: ApiSession,
  ws: string,
  label: string,
  access: AccessLevel = "authenticated",
  groups: string[] = [],
): Promise<CollectionItem> {
  const result = await api.send("POST", collectionsPath(ws), {
    json: { name: `${MARK}-${label}`, subtitle: null, access_level: access, groups },
  });
  expect(result.status, result.text).toBe(201);
  const item = json<CollectionItem>(result);
  trackedCollections.set(item.id, { api, ws });
  return item;
}

/** PUT the access of a collection. */
export async function setAccess(
  api: ApiSession,
  ws: string,
  col: string,
  access: AccessLevel,
  groups: string[],
  extra: Record<string, unknown> = {},
): ReturnType<ApiSession["send"]> {
  return api.send("PUT", `${collectionsPath(ws)}/${col}/access`, {
    json: { access_level: access, groups, ...extra },
  });
}

/**
 * PUT the access straight at the API port (no admin proxy, so no 60 s gateway timeout). Returns the status and
 * the duration of the call.
 */
export async function setAccessDirect(
  api: ApiSession,
  ws: string,
  col: string,
  access: AccessLevel,
  groups: string[],
): Promise<{ status: number; ms: number; text: string }> {
  const port = process.env.API_PORT ?? "8000";
  const cookie = [...api.jar].map(([key, value]) => `${key}=${value}`).join("; ");
  const started = Date.now();
  const response = await fetch(
    `http://127.0.0.1:${port}/workspaces/${ws}/collections/${col}/access`,
    {
      method: "PUT",
      headers: {
        cookie,
        "content-type": "application/json",
        origin: new URL(ADMIN).origin,
        "x-csrf-token": api.jar.get("ei_csrf") ?? "",
      },
      body: JSON.stringify({ access_level: access, groups }),
    },
  );
  return { status: response.status, ms: Date.now() - started, text: await response.text() };
}

/** Access level and groups of a collection as the API reports them. */
export async function accessOf(
  api: ApiSession,
  ws: string,
  col: string,
): Promise<{ access_level: string; groups: string[] }> {
  const result = await api.send("GET", collectionsPath(ws));
  expect(result.status, result.text).toBe(200);
  const item = json<{ collections: CollectionItem[] }>(result).collections.find(
    (entry) => entry.id === col,
  );
  expect(item, `collection ${col} in the list`).toBeTruthy();
  const found = item as CollectionItem;
  return { access_level: found.access_level, groups: found.groups };
}

/** Uploads a file (expects 201), tracks the document for cleanup. */
export async function uploadDoc(
  api: ApiSession,
  loc: Loc,
  name: string,
  body: Buffer,
): Promise<DocumentItem> {
  const result = await uploadRaw(api, loc, name, body);
  expect(result.status, `${name}: ${result.text}`).toBe(201);
  const item = json<DocumentItem>(result);
  trackDoc(item.id, { api, ws: loc.ws, col: loc.col });
  return item;
}

/** Upload and wait until the document is Ready (the text processing of EA-33). */
export async function readyDoc(
  api: ApiSession,
  loc: Loc,
  name: string,
  body: Buffer,
): Promise<DocumentItem> {
  const queued = await uploadDoc(api, loc, name, body);
  const done = await waitStatus(api, loc.ws, loc.col, queued.id);
  expect(done.status, `${name}: ${JSON.stringify(done)}`).toBe("ready");
  return done;
}

export async function removeDoc(api: ApiSession, loc: Loc, id: string): Promise<number> {
  const result = await deleteDoc(api, loc.ws, loc.col, id);
  if (result.status === 204) trackedDocs.delete(id);
  return result.status;
}

export async function readyCountOf(api: ApiSession, ws: string, col: string): Promise<number> {
  const result = await api.send("GET", collectionsPath(ws));
  expect(result.status, result.text).toBe(200);
  const item = json<{ collections: CollectionItem[] }>(result).collections.find(
    (entry) => entry.id === col,
  );
  expect(item, `collection ${col} in the list`).toBeTruthy();
  return (item as CollectionItem).documents.ready;
}

export { getDoc };

// ---------------------------------------------------------------------------------------------
// Operator CLI: ei-ai index ...
// ---------------------------------------------------------------------------------------------

/** `docker compose exec -T [-e K=V] api ei-ai index <args>` */
export function indexCli(args: string[], env: Record<string, string> = {}): Run {
  const envArgs = Object.entries(env).flatMap(([key, value]) => ["-e", `${key}=${value}`]);
  return compose(["exec", "-T", ...envArgs, "api", "ei-ai", "index", ...args]);
}

export type IndexStatus = {
  ready_documents: number;
  indexed: number;
  not_indexed: number;
  stale: number;
  vectors: number;
  model: string;
};

export const STATUS_RE =
  /^ready_documents=(\d+) indexed=(\d+) not_indexed=(\d+) stale=(\d+) vectors=(\d+) model=(\S+)$/;

export function parseStatus(run: Run): IndexStatus {
  expect(run.status, `index status: ${run.stderr}`).toBe(0);
  const out = lines(run.stdout);
  expect(out, `index status output: ${run.stdout}`).toHaveLength(1);
  const match = STATUS_RE.exec(out[0] ?? "");
  expect(match, `index status line: ${out[0]}`).not.toBeNull();
  const [, ready, indexed, notIndexed, stale, vectors, model] = match as RegExpExecArray;
  return {
    ready_documents: Number(ready),
    indexed: Number(indexed),
    not_indexed: Number(notIndexed),
    stale: Number(stale),
    vectors: Number(vectors),
    model: model as string,
  };
}

export function indexStatus(org: string, documentId?: string): IndexStatus {
  const args = ["status", "--org", org];
  if (documentId) args.push("--document", documentId);
  return parseStatus(indexCli(args));
}

export type Reindex = {
  run: Run;
  indexed: { id: string; vectors: number }[];
  failed: { id: string; code: string }[];
  done: { documents: number; vectors: number; failed: number; model: string } | null;
  other: string[];
};

const INDEXED_RE = new RegExp(`^indexed: (${UUID}) vectors=(\\d+)$`);
const FAILED_RE = new RegExp(`^failed: (${UUID}) \\((.+)\\)$`);
const DONE_RE = /^done: documents=(\d+) vectors=(\d+) failed=(\d+) model=(\S+)$/;

export function reindex(
  org: string,
  documentId?: string,
  env: Record<string, string> = {},
): Reindex {
  const args = ["reindex", "--org", org];
  if (documentId) args.push("--document", documentId);
  const run = indexCli(args, env);
  const result: Reindex = { run, indexed: [], failed: [], done: null, other: [] };
  for (const line of lines(run.stdout)) {
    const indexed = INDEXED_RE.exec(line);
    const failed = FAILED_RE.exec(line);
    const done = DONE_RE.exec(line);
    if (indexed) result.indexed.push({ id: indexed[1] as string, vectors: Number(indexed[2]) });
    else if (failed) result.failed.push({ id: failed[1] as string, code: failed[2] as string });
    else if (done) {
      result.done = {
        documents: Number(done[1]),
        vectors: Number(done[2]),
        failed: Number(done[3]),
        model: done[4] as string,
      };
    } else result.other.push(line);
  }
  return result;
}

export type Hit = {
  rank: number;
  distance: number;
  document: string;
  chunk: string;
  ordinal: number;
  collection: string;
  line: string;
};

const HIT_RE = new RegExp(
  `^(\\d+) distance=(\\d+\\.\\d{4}) document=(${UUID}) chunk=(${UUID}) ordinal=(\\d+) collection=(${UUID})$`,
);

export function isHitLine(line: string): boolean {
  return HIT_RE.test(line);
}

export function indexSearch(
  org: string,
  query: string,
  options: { k?: number; collection?: string } = {},
): { run: Run; hits: Hit[]; nonHitLines: string[] } {
  const args = ["search", "--org", org, "--query", query];
  if (options.k !== undefined) args.push("--k", String(options.k));
  if (options.collection) args.push("--collection", options.collection);
  const run = indexCli(args);
  const hits: Hit[] = [];
  const nonHitLines: string[] = [];
  for (const line of lines(run.stdout)) {
    const match = HIT_RE.exec(line);
    if (!match) {
      nonHitLines.push(line);
      continue;
    }
    hits.push({
      rank: Number(match[1]),
      distance: Number(match[2]),
      document: match[3] as string,
      chunk: match[4] as string,
      ordinal: Number(match[5]),
      collection: match[6] as string,
      line,
    });
  }
  return { run, hits, nonHitLines };
}

/** Polls `index status --document` every 2 s until `indexed=1`; returns the time it took. */
export async function waitIndexed(
  org: string,
  documentId: string,
  timeoutMs = INDEX_DEADLINE_MS,
  onPoll?: () => Promise<void>,
): Promise<{ status: IndexStatus; elapsedMs: number }> {
  const started = Date.now();
  let last: IndexStatus | undefined;
  while (Date.now() - started <= timeoutMs) {
    last = indexStatus(org, documentId);
    if (last.indexed === 1) return { status: last, elapsedMs: Date.now() - started };
    if (onPoll) await onPoll();
    await sleep(POLL_MS);
  }
  throw new Error(
    `document ${documentId} not indexed within ${timeoutMs} ms: last ${JSON.stringify(last)}`,
  );
}

// ---------------------------------------------------------------------------------------------
// SQL as the superuser
// ---------------------------------------------------------------------------------------------

export function vectorCount(documentId: string): number {
  return Number(sql(`select count(*) from chunk_embeddings where document_id = '${documentId}'`));
}

export type VectorRow = {
  org_id: string;
  collection_id: string;
  workspace_id: string;
  folder_id: string;
  document_id: string;
  access_level: string;
  groups: string[];
  model_id: string;
  model_version: string;
};

/** Vectors of a document or of a whole collection (`by`), with the columns of the contract. */
export function vectorRows(by: { documentId: string } | { collectionId: string }): VectorRow[] {
  const where =
    "documentId" in by
      ? `document_id = '${by.documentId}'`
      : `collection_id = '${by.collectionId}'`;
  const out = sql(
    `select coalesce(json_agg(t), '[]'::json) from (
       select org_id, collection_id, workspace_id, folder_id, document_id, access_level, groups, model_id, model_version
       from chunk_embeddings where ${where}) t`,
  );
  return JSON.parse(out) as VectorRow[];
}

/** "count|md5 of (id, created_at)" of the vectors matching a SQL condition: equal before/after = unchanged. */
export function fingerprint(condition: string): string {
  return sql(
    `select count(*) || '|' || coalesce(md5(string_agg(id::text || '/' || created_at::text, ',' order by id)), '-')
       from chunk_embeddings where ${condition}`,
  );
}

/** "count|md5 of (id, access_level, groups)": access metadata of the vectors matching a condition. */
export function accessFingerprint(condition: string): string {
  return sql(
    `select count(*) || '|' || coalesce(md5(string_agg(id::text || '/' || access_level || '/' || groups::text, ',' order by id)), '-')
       from chunk_embeddings where ${condition}`,
  );
}

export function vectorIds(condition: string): string[] {
  return rows(`select id from chunk_embeddings where ${condition} order by id`);
}

export function orgOfDocument(documentId: string): string {
  return sql(`select org_id from documents where id = '${documentId}'`);
}

export function sameSet(actual: string[], expected: string[]): void {
  expect([...actual].sort()).toEqual([...expected].sort());
}

export type Counts = {
  vectors: number;
  chunks: number;
  documents: number;
  folders: number;
  collections: number;
  audit: number;
};

export function counts(): Counts {
  return {
    vectors: Number(sql("select count(*) from chunk_embeddings")),
    chunks: Number(sql("select count(*) from document_chunks")),
    documents: Number(sql("select count(*) from documents")),
    folders: Number(sql("select count(*) from folders")),
    collections: Number(sql("select count(*) from collections")),
    audit: Number(
      sql(
        "select count(*) from audit_events where action like 'document.%' or action like 'folder.%' or action like 'collection.%'",
      ),
    ),
  };
}

/** Rows of documents, folders and collections that still carry the marker; vectors without a document. */
export function markerRows(): string[] {
  const like = "'%qa-ea35-%'";
  return rows(
    `select 'document' from documents d where to_jsonb(d)::text ilike ${like}
     union all select 'folder' from folders f where to_jsonb(f)::text ilike ${like}
     union all select 'collection' from collections c where to_jsonb(c)::text ilike ${like}
     union all select 'orphan vector' from chunk_embeddings e where not exists (select 1 from documents d where d.id = e.document_id)`,
  );
}

/** Removes everything this run created: documents (vectors go with them), folders, collections, audit rows. */
export async function cleanupAll(): Promise<void> {
  for (const [id, owner] of [...trackedDocs]) {
    try {
      await deleteDoc(owner.api, owner.ws, owner.col, id);
    } catch {
      // the SQL fallback below removes what is left
    }
  }
  for (const folder of [...trackedFolders].reverse()) {
    try {
      await folder.api.send(
        "DELETE",
        `${collectionsPath(folder.ws)}/${folder.col}/folders/${folder.id}`,
      );
    } catch {
      // retried through SQL
    }
  }
  for (const [id, owner] of trackedCollections) {
    try {
      await owner.api.send("DELETE", `${collectionsPath(owner.ws)}/${id}`);
    } catch {
      // retried through SQL
    }
  }
  const ids = [
    ...trackedDocs.keys(),
    ...trackedFolders.map((folder) => folder.id),
    ...trackedCollections.keys(),
  ];
  const quoted = ids.map((id) => `'${id}'`).join(", ");
  const like = "'%qa-ea35-%'";
  const docs = `select id from documents d where to_jsonb(d)::text ilike ${like}${
    trackedDocs.size > 0
      ? ` or id::text in (${[...trackedDocs.keys()].map((id) => `'${id}'`).join(", ")})`
      : ""
  }`;
  const statements = [
    `delete from chunk_embeddings where document_id in (${docs})`,
    `delete from document_chunks where document_id in (${docs})`,
    `delete from documents where id in (${docs})`,
  ];
  if (ids.length > 0)
    statements.push(`delete from audit_events where target_id::text in (${quoted})`);
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
  trackedDocs.clear();
  trackedFolders.length = 0;
  trackedCollections.clear();
}

// ---------------------------------------------------------------------------------------------
// Compose helpers for the embedding service
// ---------------------------------------------------------------------------------------------

export function embeddingHealthy(): boolean {
  return /\(healthy\)/.test(compose(["ps", "embedding"]).stdout);
}

export async function waitEmbeddingHealthy(timeoutMs = 240_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (embeddingHealthy()) return;
    await sleep(3000);
  }
  throw new Error("embedding service did not become healthy");
}

// ---------------------------------------------------------------------------------------------
// Test text (Vietnamese, NFC)
// ---------------------------------------------------------------------------------------------

/** About `chars` characters of distinct Vietnamese sentences about annual leave requests. */
export function leaveText(chars: number, tag = ""): string {
  const paragraphs: string[] = [];
  let total = 0;
  let n = 1;
  while (total < chars) {
    const p =
      `Điều ${n}. Đơn xin nghỉ phép năm ${tag} phải được gửi cho quản lý trực tiếp ít nhất ba ngày làm việc trước ngày nghỉ. ` +
      `Nhân viên có mười hai ngày phép mỗi năm, và ngày phép chưa dùng được chuyển sang quý sau tối đa năm ngày (mục ${n}). ` +
      `Quản lý phê duyệt đơn trong vòng hai ngày làm việc và phòng nhân sự cập nhật số ngày phép còn lại.\n\n`;
    paragraphs.push(p);
    total += p.length;
    n += 1;
  }
  return paragraphs.join("").trim();
}

/** About `chars` characters of Vietnamese about passwords and two-factor authentication (another topic). */
export function securityText(chars: number): string {
  const paragraphs: string[] = [];
  let total = 0;
  let n = 1;
  while (total < chars) {
    const p =
      `Mục ${n}. Mật khẩu của tài khoản công ty phải có ít nhất mười hai ký tự và được thay đổi khi nghi ngờ bị lộ. ` +
      `Xác thực hai lớp là bắt buộc đối với mọi hệ thống nội bộ; không chia sẻ mã xác thực với bất kỳ ai (điều ${n}). ` +
      `Thiết bị mất cắp phải được báo cho bộ phận bảo mật ngay lập tức để khóa quyền truy cập.\n\n`;
    paragraphs.push(p);
    total += p.length;
    n += 1;
  }
  return paragraphs.join("").trim();
}

export function txt(text: string): Buffer {
  return Buffer.from(text, "utf8");
}

export type Context = {
  ws: string;
  /** Employee Handbook of People Ops (seed collection; the specs only add their own folders to it). */
  col: string;
  linh: ApiSession;
  thao: ApiSession;
  ngan: ApiSession;
};

/** Sessions plus the People Ops workspace and its Employee Handbook collection. */
export async function setupContext(): Promise<Context> {
  const ws = peopleOpsId();
  const linh = await apiOf("linh");
  const thao = await apiOf("thao");
  const ngan = await apiOf("ngan");
  const result = await linh.send("GET", collectionsPath(ws));
  expect(result.status, result.text).toBe(200);
  const handbook = json<{ collections: CollectionItem[] }>(result).collections.find(
    (entry) => entry.name === "Employee Handbook",
  );
  expect(handbook, "precondition: the demo seed created Employee Handbook").toBeTruthy();
  return { ws, col: (handbook as CollectionItem).id, linh, thao, ngan };
}
