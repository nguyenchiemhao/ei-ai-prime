// EA-36 (KB-05): helpers of the permission-filtered retrieval specs. Black-box only: the admin origin (the
// /api proxy used by the EA-32/EA-33 helpers), the operator CLI `ei-ai index retrieve` through
// `docker compose exec`, psql as the database superuser and the container logs. Builds on ./ea22, ./ea32,
// ./ea33 and ./ea35 (sessions, upload helpers, `indexCli`, `waitIndexed`, `setAccess`).
// Everything a run creates carries the marker `qa-EA36-<run>` (collection, folder and file names), so
// cleanup36() and markerRows36() can find it. Seed rows are never changed.
//
// Draft location: .work/EA-36/e2e-draft/support/ea36.ts; the `run` mode moves it to e2e/support/ea36.ts.
import { expect } from "@playwright/test";
import {
  DEMO_ORG,
  RUN,
  UUID,
  lines,
  peopleOpsId,
  rows,
  sql,
  type ApiSession,
  type Run,
} from "./ea22";
import { collectionsPath, json, type CollectionItem, type FolderItem } from "./ea32";
import {
  SONGHAN_ORG,
  apiOf,
  chunksOf,
  deleteDoc,
  uploadRaw,
  waitStatus,
  type DocumentItem,
  type Loc,
} from "./ea33";
import { indexCli, waitIndexed, type AccessLevel } from "./ea35";

export { DEMO_ORG, RUN, SONGHAN_ORG, UUID };
export const MARK36 = `qa-EA36-${RUN}`;
export const MAX_CANDIDATES = 20;
export const DEFAULT_K = 4;
/** Indexing deadline for the ordinary fixtures (the 120 s of EA-35 AC1 plus a margin for a busy CPU). */
export const FIXTURE_INDEX_MS = 240_000;
/** Indexing deadline of the 100+ chunk flood file. */
export const FLOOD_INDEX_MS = 900_000;
/** Exact message of the configuration error (contract, exit 1). */
export const RERANK_CONFIG_ERROR =
  "configuration error: RERANK_MODEL_REF must name a local rerank model of the platform manifest";
/** The reranker the contract says is configured but not served in this setup. */
export const RERANK_UNREACHABLE_REF = "bge-reranker-v2-m3@2026.10";

// ---------------------------------------------------------------------------------------------
// Test text: one distinct topic sentence per collection, repeated in every paragraph
// ---------------------------------------------------------------------------------------------

export type Topic = { sentence: string; query: string };
export const TOPIC: Record<"P" | "A" | "M" | "H" | "X", Topic> = {
  P: {
    sentence:
      "The company offices are open from 8:30 to 17:30, Monday to Friday, and closed on public holidays.",
    query: "office opening hours",
  },
  A: {
    sentence:
      "Every employee receives twelve days of annual leave per year and may carry five unused days into the next quarter.",
    query: "annual leave days",
  },
  M: {
    sentence:
      "Salary review bands are decided every January and only managers may see the pay band of each grade.",
    query: "salary review bands",
  },
  H: {
    sentence:
      "The disciplinary process begins with a written warning followed by a formal hearing with the HR team.",
    query: "disciplinary process",
  },
  X: {
    sentence:
      "Expense claims must be submitted with the original receipts within thirty days of the purchase.",
    query: "expense claims",
  },
};
export const VI_P_SENTENCE =
  "Văn phòng mở cửa từ 8 giờ 30 đến 17 giờ 30, từ thứ Hai đến thứ Sáu, và nghỉ vào các ngày lễ.";

const FILL = [
  "Ask the people team if anything is unclear.",
  "This rule applies to every site of the company.",
  "The rule is reviewed once a year by the leadership team.",
  "Exceptions need a written approval from the line manager.",
  "Contractors follow the same rule unless their contract says otherwise.",
  "Questions can be sent to the internal help desk.",
];

/** `count` paragraphs, each with the topic sentence and one filler sentence. */
export function topicBody(sentence: string, count: number, tag: string): string {
  const paragraphs: string[] = [];
  for (let n = 1; n <= count; n += 1) {
    paragraphs.push(`${tag} section ${n}. ${sentence} ${FILL[n % FILL.length] as string}`);
  }
  return paragraphs.join("\n\n");
}

/** `count` paragraphs that are nothing but the sentence repeated: the best possible match for the sentence. */
export function floodBody(sentence: string, count: number): string {
  const paragraphs: string[] = [];
  for (let n = 1; n <= count; n += 1) {
    paragraphs.push(`Item ${n}. ${[sentence, sentence, sentence, sentence].join(" ")}`);
  }
  return paragraphs.join("\n\n");
}

export function norm(text: string): string {
  return text.replace(/\s+/g, " ").trim().toLowerCase();
}

// ---------------------------------------------------------------------------------------------
// Tracked writes: everything created is deleted again by cleanup36()
// ---------------------------------------------------------------------------------------------

type Owner = { api: ApiSession; ws: string; col: string };
const trackedDocs = new Map<string, Owner>();
const trackedFolders: { id: string; api: ApiSession; ws: string; col: string }[] = [];
const trackedCollections = new Map<string, { api: ApiSession; ws: string }>();
const everIds = new Set<string>();
const RUN_STARTED = new Date(Date.now() - 5000).toISOString();

export async function makeCollection(
  api: ApiSession,
  ws: string,
  label: string,
  access: AccessLevel,
  groups: string[] = [],
): Promise<CollectionItem> {
  const result = await api.send("POST", collectionsPath(ws), {
    json: {
      name: `${MARK36}-${label}`,
      subtitle: null,
      access_level: access,
      groups,
      local_only: false,
    },
  });
  expect(result.status, result.text).toBe(201);
  const item = json<CollectionItem>(result);
  trackedCollections.set(item.id, { api, ws });
  everIds.add(item.id);
  return item;
}

export async function makeFolder(
  api: ApiSession,
  ws: string,
  col: string,
  label: string,
  parentId: string | null = null,
): Promise<FolderItem> {
  const result = await api.send("POST", `${collectionsPath(ws)}/${col}/folders`, {
    json: { name: `${MARK36}-${label}`, parent_id: parentId },
  });
  expect(result.status, result.text).toBe(201);
  const folder = json<FolderItem>(result);
  trackedFolders.push({ id: folder.id, api, ws, col });
  everIds.add(folder.id);
  return folder;
}

/** Upload (expects 201) and wait for `ready`; the document is tracked for cleanup. */
export async function uploadReady(
  api: ApiSession,
  loc: Loc,
  name: string,
  body: string,
): Promise<DocumentItem> {
  const result = await uploadRaw(api, loc, name, Buffer.from(body, "utf8"));
  expect(result.status, `${name}: ${result.text}`).toBe(201);
  const queued = json<DocumentItem>(result);
  trackedDocs.set(queued.id, { api, ws: loc.ws, col: loc.col });
  everIds.add(queued.id);
  const done = await waitStatus(api, loc.ws, loc.col, queued.id);
  expect(done.status, `${name}: ${JSON.stringify(done)}`).toBe("ready");
  return done;
}

export async function removeDoc(api: ApiSession, loc: Loc, id: string): Promise<void> {
  const result = await deleteDoc(api, loc.ws, loc.col, id);
  expect(result.status, result.text).toBe(204);
  trackedDocs.delete(id);
}

export type DocRef = { id: string; chunks: number };

/**
 * Uploads a TXT built by `build(paragraphs)` until at least `minChunks` of its chunks contain `contains`
 * (the chunk size is not part of the contract, so the file grows: start, 2x, 4x ...), then waits until the
 * document is indexed. Failed attempts are deleted again.
 */
export async function addDoc(
  api: ApiSession,
  org: string,
  loc: Loc,
  name: string,
  build: (paragraphs: number) => string,
  options: {
    contains: string;
    minChunks: number;
    start: number;
    indexTimeoutMs?: number;
  },
): Promise<DocRef> {
  let paragraphs = options.start;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const doc = await uploadReady(api, loc, name, build(paragraphs));
    const chunks = await chunksOf(api, loc.ws, loc.col, doc.id);
    const matching = chunks.filter((chunk) => norm(chunk.text).includes(norm(options.contains)));
    if (matching.length >= options.minChunks) {
      await waitIndexed(org, doc.id, options.indexTimeoutMs ?? FIXTURE_INDEX_MS);
      return { id: doc.id, chunks: chunks.length };
    }
    await removeDoc(api, loc, doc.id);
    paragraphs *= 2;
  }
  throw new Error(`${name}: fewer than ${options.minChunks} chunks contain the topic sentence`);
}

// ---------------------------------------------------------------------------------------------
// Fixtures of the contract: P, A, M, H, X in People Ops (Mekong), one public collection per other scope
// ---------------------------------------------------------------------------------------------

export type Placed = { id: string; folder: string; doc: DocRef };
export type Fixtures = {
  ws: string;
  shWs: string;
  engWs: string;
  linh: ApiSession;
  quang: ApiSession;
  ngan: ApiSession;
  /** P public: an English file with the exact sentence in >= 6 chunks, plus a Vietnamese file. */
  p: Placed & { vi: DocRef };
  a: Placed;
  /** M restricted ["Managers"], stored as ["managers"]; >= 6 chunks carry the exact sentence. */
  m: Placed;
  /** H restricted ["hr"]. */
  h: Placed;
  /** X authenticated, folders f1 (sub-folder f1a) and f2, one file each. */
  x: { id: string; f1: string; f1a: string; f2: string; d1: DocRef; d1a: DocRef; d2: DocRef };
  /** A public collection of Sông Hàn Retail with the same sentence as P (cross-tenant bait). */
  sh: Placed;
  /** A public collection of Mekong's Workspace Engineering with the same sentence as P (cross-Workspace bait). */
  eng: Placed;
  /** [P, A, M, H, X]: the explicit scope of most cases. */
  scope: string[];
};

function loc(ws: string, col: string, folder: string): Loc {
  return { ws, col, folder };
}

export function workspaceIdOf(org: string, name: string): string {
  const id = rows(`select id from workspaces where org_id = '${org}' and name = '${name}'`)[0];
  expect(id, `precondition: Workspace ${name} of ${org}`).toBeTruthy();
  return id as string;
}

export async function buildFixtures(): Promise<Fixtures> {
  const ws = peopleOpsId();
  const shWs = workspaceIdOf(SONGHAN_ORG, "Customer Care");
  const engWs = workspaceIdOf(DEMO_ORG, "Engineering");
  const linh = await apiOf("linh");
  const quang = await apiOf("quang");
  const ngan = await apiOf("ngan");

  const place = async (
    api: ApiSession,
    org: string,
    space: string,
    label: string,
    access: AccessLevel,
    groups: string[],
    topic: Topic,
    minChunks: number,
    start: number,
  ): Promise<Placed> => {
    const col = await makeCollection(api, space, label, access, groups);
    const folder = await makeFolder(api, space, col.id, `${label}-folder`);
    const doc = await addDoc(
      api,
      org,
      loc(space, col.id, folder.id),
      `${MARK36}-${label}.txt`,
      (n) => topicBody(topic.sentence, n, label),
      { contains: topic.sentence, minChunks, start },
    );
    return { id: col.id, folder: folder.id, doc };
  };

  const p = await place(linh, DEMO_ORG, ws, "public", "public", [], TOPIC.P, 6, 24);
  const viDoc = await addDoc(
    linh,
    DEMO_ORG,
    loc(ws, p.id, p.folder),
    `${MARK36}-public-vi.txt`,
    (n) => topicBody(VI_P_SENTENCE, n, "vi"),
    { contains: VI_P_SENTENCE, minChunks: 1, start: 6 },
  );
  const a = await place(linh, DEMO_ORG, ws, "auth", "authenticated", [], TOPIC.A, 2, 8);
  const m = await place(linh, DEMO_ORG, ws, "managers", "restricted", ["Managers"], TOPIC.M, 6, 24);
  const h = await place(linh, DEMO_ORG, ws, "hr", "restricted", ["hr"], TOPIC.H, 2, 8);

  const xCol = await makeCollection(linh, ws, "other", "authenticated");
  const f1 = await makeFolder(linh, ws, xCol.id, "other-f1");
  const f1a = await makeFolder(linh, ws, xCol.id, "other-f1a", f1.id);
  const f2 = await makeFolder(linh, ws, xCol.id, "other-f2");
  const xOptions = { contains: TOPIC.X.sentence, minChunks: 1, start: 3 };
  const d1 = await addDoc(
    linh,
    DEMO_ORG,
    loc(ws, xCol.id, f1.id),
    `${MARK36}-x-f1.txt`,
    (n) => topicBody(TOPIC.X.sentence, n, "f1"),
    xOptions,
  );
  const d1a = await addDoc(
    linh,
    DEMO_ORG,
    loc(ws, xCol.id, f1a.id),
    `${MARK36}-x-f1a.txt`,
    (n) => topicBody(TOPIC.X.sentence, n, "f1a"),
    xOptions,
  );
  const d2 = await addDoc(
    linh,
    DEMO_ORG,
    loc(ws, xCol.id, f2.id),
    `${MARK36}-x-f2.txt`,
    (n) => topicBody(TOPIC.X.sentence, n, "f2"),
    xOptions,
  );

  const sh = await place(ngan, SONGHAN_ORG, shWs, "sh-public", "public", [], TOPIC.P, 1, 6);
  const eng = await place(quang, DEMO_ORG, engWs, "eng-public", "public", [], TOPIC.P, 1, 6);

  return {
    ws,
    shWs,
    engWs,
    linh,
    quang,
    ngan,
    p: { ...p, vi: viDoc },
    a,
    m,
    h,
    x: { id: xCol.id, f1: f1.id, f1a: f1a.id, f2: f2.id, d1, d1a, d2 },
    sh,
    eng,
    scope: [p.id, a.id, m.id, h.id, xCol.id],
  };
}

// ---------------------------------------------------------------------------------------------
// Operator CLI: ei-ai index retrieve
// ---------------------------------------------------------------------------------------------

export type Retrieve = {
  org?: string;
  ws: string;
  query: string;
  /** `anonymous`, `authenticated` or (for validation cases) any other text. Default `anonymous`. */
  as?: string;
  groups?: string[];
  collections?: string[];
  folders?: string[];
  k?: number | string;
  /** Environment of the `docker compose exec` call (RERANK_MODEL_REF). */
  env?: Record<string, string>;
};

export function retrieveArgs(o: Retrieve): string[] {
  const args = [
    "--org",
    o.org ?? DEMO_ORG,
    "--workspace",
    o.ws,
    "--query",
    o.query,
    "--as",
    o.as ?? "anonymous",
  ];
  for (const group of o.groups ?? []) args.push("--group", group);
  for (const id of o.collections ?? []) args.push("--collection", id);
  for (const id of o.folders ?? []) args.push("--folder", id);
  if (o.k !== undefined) args.push("--k", String(o.k));
  return args;
}

export function retrieveRaw(args: string[], env: Record<string, string> = {}): Run {
  return indexCli(["retrieve", ...args], env);
}

export type Skipped = {
  id: string;
  kind: "collection" | "folder";
  reason: "no_access" | "not_found";
};
export type Passage = {
  rank: number;
  chunk: string;
  document: string;
  collection: string;
  ordinal: number;
  score: number;
  rerank: number | null;
  line: string;
};
export type Done = {
  searched: number;
  skipped: number;
  candidates: number;
  passages: number;
  retrieval: string;
  rerank: "off" | "applied" | "unavailable";
};
export type Retrieval = {
  run: Run;
  principal: { as: "anonymous" | "authenticated"; groups: number } | null;
  searched: string[];
  skipped: Skipped[];
  passages: Passage[];
  done: Done | null;
  /** stdout lines that match none of the five line formats of the contract. */
  unparsed: string[];
  /** The kinds of the parsed lines in the order they were printed. */
  order: string[];
};

const PRINCIPAL_RE = /^principal: (anonymous|authenticated) groups=(\d+) simulated=yes$/;
const SEARCHED_RE = new RegExp(`^searched: (${UUID})$`);
const SKIPPED_RE = new RegExp(
  `^skipped: (${UUID}) kind=(collection|folder) reason=(no_access|not_found)$`,
);
const PASSAGE_RE = new RegExp(
  `^passage: (\\d+) chunk=(${UUID}) document=(${UUID}) collection=(${UUID}) ordinal=(\\d+) score=(\\d+\\.\\d{4}) rerank=(\\d+\\.\\d{4}|-)$`,
);
const DONE_RE =
  /^done: searched=(\d+) skipped=(\d+) candidates=(\d+) passages=(\d+) retrieval=(\S+) rerank=(off|applied|unavailable)$/;

export function parseRetrieval(run: Run): Retrieval {
  const result: Retrieval = {
    run,
    principal: null,
    searched: [],
    skipped: [],
    passages: [],
    done: null,
    unparsed: [],
    order: [],
  };
  for (const line of lines(run.stdout)) {
    let match: RegExpExecArray | null;
    if ((match = PRINCIPAL_RE.exec(line))) {
      result.principal = {
        as: match[1] as "anonymous" | "authenticated",
        groups: Number(match[2]),
      };
      result.order.push("principal");
    } else if ((match = SEARCHED_RE.exec(line))) {
      result.searched.push(match[1] as string);
      result.order.push("searched");
    } else if ((match = SKIPPED_RE.exec(line))) {
      result.skipped.push({
        id: match[1] as string,
        kind: match[2] as Skipped["kind"],
        reason: match[3] as Skipped["reason"],
      });
      result.order.push("skipped");
    } else if ((match = PASSAGE_RE.exec(line))) {
      result.passages.push({
        rank: Number(match[1]),
        chunk: match[2] as string,
        document: match[3] as string,
        collection: match[4] as string,
        ordinal: Number(match[5]),
        score: Number(match[6]),
        rerank: match[7] === "-" ? null : Number(match[7]),
        line,
      });
      result.order.push("passage");
    } else if ((match = DONE_RE.exec(line))) {
      result.done = {
        searched: Number(match[1]),
        skipped: Number(match[2]),
        candidates: Number(match[3]),
        passages: Number(match[4]),
        retrieval: match[5] as string,
        rerank: match[6] as Done["rerank"],
      };
      result.order.push("done");
    } else {
      result.unparsed.push(line);
    }
  }
  return result;
}

/** Runs the command and parses stdout. Never echoing the query is checked on every run. */
export function retrieve(o: Retrieve): Retrieval {
  const run = retrieveRaw(retrieveArgs(o), o.env);
  expectQueryNotEchoed(run, o.query);
  return parseRetrieval(run);
}

/** The query (and its words in a row) must not appear in stdout or stderr: ids and numbers only. */
export function expectQueryNotEchoed(run: Run, query: string): void {
  if (query.trim().length < 8) return;
  const output = `${run.stdout}\n${run.stderr}`.toLowerCase();
  expect(output, "the CLI output must not echo the query").not.toContain(
    query.trim().toLowerCase(),
  );
}

const KIND_RANK: Record<string, number> = {
  principal: 0,
  searched: 1,
  skipped: 1,
  passage: 2,
  done: 3,
};

/** Structure shared by every successful run (exit 0): formats, order, counts, ranks, scores. */
export function expectWellFormed(
  r: Retrieval,
  expected: {
    as: "anonymous" | "authenticated";
    groups?: number;
    k?: number;
    rerank?: Done["rerank"];
  },
): void {
  expect(r.run.status, `exit code; stderr: ${r.run.stderr}`).toBe(0);
  expect(r.run.stderr, "no traceback").not.toMatch(/Traceback/);
  expect(r.unparsed, "stdout holds only the five line formats").toEqual([]);
  expect(r.principal, "principal line").not.toBeNull();
  expect(r.principal?.as).toBe(expected.as);
  if (expected.groups !== undefined)
    expect(r.principal?.groups, "groups=<n>").toBe(expected.groups);
  expect(r.done, "done line").not.toBeNull();
  const done = r.done as Done;
  expect(r.order[0], "principal is the first line").toBe("principal");
  expect(r.order[r.order.length - 1], "done is the last line").toBe("done");
  expect(r.order.filter((kind) => kind === "principal")).toHaveLength(1);
  expect(r.order.filter((kind) => kind === "done")).toHaveLength(1);
  const ranks = r.order.map((kind) => KIND_RANK[kind] as number);
  expect(ranks, "order: principal, searched/skipped, passages, done").toEqual(
    [...ranks].sort((x, y) => x - y),
  );
  expect(done.searched, "done.searched = searched lines").toBe(r.searched.length);
  expect(done.skipped, "done.skipped = skipped lines").toBe(r.skipped.length);
  expect(done.passages, "done.passages = passage lines").toBe(r.passages.length);
  expect(done.retrieval).toBe("vector");
  expect(done.rerank).toBe(expected.rerank ?? "off");
  expect(done.candidates).toBeLessThanOrEqual(MAX_CANDIDATES);
  expect(done.candidates).toBeGreaterThanOrEqual(done.passages);
  expect(r.passages.length).toBeLessThanOrEqual(expected.k ?? DEFAULT_K);
  // No similarity threshold: every permitted candidate is returned, best first, up to k.
  expect(done.passages, "passages = min(k, candidates)").toBe(
    Math.min(expected.k ?? DEFAULT_K, done.candidates),
  );
  expect(new Set(r.searched).size, "no collection searched twice").toBe(r.searched.length);
  expect(new Set(r.passages.map((p) => p.chunk)).size, "no chunk twice").toBe(r.passages.length);
  r.passages.forEach((passage, index) => {
    expect(passage.rank, "ranks run 1..n").toBe(index + 1);
    expect(passage.score).toBeGreaterThanOrEqual(0);
    expect(passage.score).toBeLessThanOrEqual(1);
    if (index > 0) {
      expect(passage.score, "best first").toBeLessThanOrEqual(
        (r.passages[index - 1] as Passage).score,
      );
    }
    expect(
      r.searched.includes(passage.collection),
      "a passage comes from a searched collection",
    ).toBe(true);
    if ((expected.rerank ?? "off") !== "applied") expect(passage.rerank).toBeNull();
  });
  const skippedCollections = r.skipped.filter((s) => s.kind === "collection").map((s) => s.id);
  for (const id of skippedCollections)
    expect(r.searched, "skipped is not searched").not.toContain(id);
}

// ---------------------------------------------------------------------------------------------
// SQL oracle: the database, not the CLI, says what a principal may read
// ---------------------------------------------------------------------------------------------

export type VectorMeta = {
  chunk_id: string;
  org_id: string;
  collection_id: string;
  document_id: string;
  folder_id: string;
  access_level: string;
  groups: string[];
};

export function vectorMeta(chunkIds: string[]): Map<string, VectorMeta> {
  if (chunkIds.length === 0) return new Map();
  const list = chunkIds.map((id) => `'${id}'`).join(", ");
  const out = sql(
    `select coalesce(json_agg(t), '[]'::json) from (
       select chunk_id, org_id, collection_id, document_id, folder_id, access_level, groups
       from chunk_embeddings where chunk_id in (${list})) t`,
  );
  return new Map((JSON.parse(out) as VectorMeta[]).map((row) => [row.chunk_id, row]));
}

export function lower(groups: string[]): string[] {
  return [...new Set(groups.map((group) => group.toLowerCase()))];
}

export function mayRead(
  meta: Pick<VectorMeta, "access_level" | "groups">,
  as: "anonymous" | "authenticated",
  groups: string[],
): boolean {
  if (meta.access_level === "public") return true;
  if (as === "anonymous") return false;
  if (meta.access_level === "authenticated") return true;
  const mine = lower(groups);
  return meta.groups.some((group) => mine.includes(group));
}

/**
 * Every passage exists as a vector, belongs to the collection/document the CLI printed, to the Organization
 * asked for, and the principal is allowed to read it (level and groups from the database).
 */
export function expectPermitted(
  r: Retrieval,
  as: "anonymous" | "authenticated",
  groups: string[] = [],
  org: string = DEMO_ORG,
): void {
  const meta = vectorMeta(r.passages.map((p) => p.chunk));
  for (const passage of r.passages) {
    const row = meta.get(passage.chunk);
    expect(row, `chunk ${passage.chunk} is an indexed vector`).toBeTruthy();
    const found = row as VectorMeta;
    expect(found.collection_id, "collection printed = collection stored").toBe(passage.collection);
    expect(found.document_id, "document printed = document stored").toBe(passage.document);
    expect(found.org_id, "same Organization").toBe(org);
    expect(
      mayRead(found, as, groups),
      `${as} [${groups.join(",")}] must not read ${found.access_level} [${found.groups.join(",")}] (chunk ${passage.chunk})`,
    ).toBe(true);
  }
}

/** Number of permitted vectors in the given collections (the most `candidates` can be, capped at 20). */
export function permittedVectors(
  org: string,
  collectionIds: string[],
  as: "anonymous" | "authenticated",
  groups: string[] = [],
): number {
  if (collectionIds.length === 0) return 0;
  const ids = collectionIds.map((id) => `'${id}'`).join(", ");
  const levels = as === "anonymous" ? "'public'" : "'public', 'authenticated'";
  const overlap =
    as === "authenticated" && groups.length > 0
      ? ` or groups && array[${lower(groups)
          .map((group) => `'${group.replace(/'/g, "''")}'`)
          .join(", ")}]::text[]`
      : "";
  return Number(
    sql(
      `select count(*) from chunk_embeddings where org_id = '${org}' and collection_id in (${ids})
         and (access_level in (${levels})${overlap})`,
    ),
  );
}

/** Chunk ids of a collection or of a document, from the database. */
export function chunkIdsOf(by: { collection: string } | { document: string }): string[] {
  const where =
    "collection" in by ? `collection_id = '${by.collection}'` : `document_id = '${by.document}'`;
  return rows(`select chunk_id from chunk_embeddings where ${where}`);
}

export function uuidsIn(text: string): string[] {
  return text.match(new RegExp(UUID, "g")) ?? [];
}

/** Output with every id replaced: two runs "look the same" when this is equal. */
export function shapeOf(run: Run): string {
  return `${run.status}|${run.stdout.replace(new RegExp(UUID, "g"), "<id>")}|${run.stderr.replace(new RegExp(UUID, "g"), "<id>")}`;
}

export function randomUuid(): string {
  const hex = (n: number): string =>
    Array.from({ length: n }, () => Math.floor(Math.random() * 16).toString(16)).join("");
  return `${hex(8)}-${hex(4)}-7${hex(3)}-8${hex(3)}-${hex(12)}`;
}

/** Ids of every collection of a Workspace, as the admin API lists them (the sessions below are org admins). */
export async function workspaceCollectionIds(api: ApiSession, ws: string): Promise<string[]> {
  const result = await api.send("GET", collectionsPath(ws));
  expect(result.status, result.text).toBe(200);
  return json<{ collections: CollectionItem[] }>(result).collections.map((entry) => entry.id);
}

// ---------------------------------------------------------------------------------------------
// Hygiene
// ---------------------------------------------------------------------------------------------

export type Counts36 = {
  chunk_embeddings: number;
  documents: number;
  document_chunks: number;
  collections: number;
  folders: number;
};

export function counts36(): Counts36 {
  const count = (table: string): number => Number(sql(`select count(*) from ${table}`));
  return {
    chunk_embeddings: count("chunk_embeddings"),
    documents: count("documents"),
    document_chunks: count("document_chunks"),
    collections: count("collections"),
    folders: count("folders"),
  };
}

/** Rows that still carry the marker, and vectors whose document is gone. */
export function markerRows36(): string[] {
  const like = "'%qa-ea36-%'";
  return rows(
    `select 'document' from documents d where to_jsonb(d)::text ilike ${like}
     union all select 'folder' from folders f where to_jsonb(f)::text ilike ${like}
     union all select 'collection' from collections c where to_jsonb(c)::text ilike ${like}
     union all select 'orphan vector' from chunk_embeddings e where not exists (select 1 from documents d where d.id = e.document_id)`,
  );
}

/** Removes everything this run created: documents (vectors go with them), folders, collections, audit rows. */
export async function cleanup36(): Promise<void> {
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
  const like = "'%qa-ea36-%'";
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
  if (everIds.size > 0) {
    const ids = [...everIds].map((id) => `'${id}'`).join(", ");
    statements.push(`delete from audit_events where target_id::text in (${ids})`);
  }
  statements.push(
    `delete from audit_events a where (action like 'folder.%' or action like 'collection.%') and created_at >= '${RUN_STARTED}' and to_jsonb(a)::text ilike ${like}`,
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
