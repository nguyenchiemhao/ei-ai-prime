// EA-36 (KB-05): test data hygiene check for the permission-filtered retrieval QA run (SQL, read only).
//   node e2e/knowledge/scripts/EA-36-permission-retrieval-hygiene.mjs            prints the row counts
//   node e2e/knowledge/scripts/EA-36-permission-retrieval-hygiene.mjs <before.txt>
//       also compares with a file saved from an earlier run of this script (`... > before.txt`)
// Exit 1 when a row carries the marker `qa-ea36`, a vector has no chunk (orphan), or the counts differ from the file.
// Needs the stack up (`docker compose ps db`). It never writes to the database.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

function sql(query) {
  const result = spawnSync(
    "docker",
    [
      "compose",
      "exec",
      "-T",
      "db",
      "psql",
      "-U",
      "postgres",
      "-d",
      "ei_ai",
      "-tA",
      "-F",
      "=",
      "-c",
      query,
    ],
    { cwd: ROOT, encoding: "utf8" },
  );
  if (result.status !== 0) throw new Error(`psql failed: ${result.stderr}`);
  return result.stdout.trim();
}

const counts = sql(
  [
    "select 'chunk_embeddings', count(*) from chunk_embeddings",
    "select 'documents', count(*) from documents",
    "select 'document_chunks', count(*) from document_chunks",
    "select 'collections', count(*) from collections",
    "select 'folders', count(*) from folders",
  ].join(" union all "),
);
const marker = sql(
  "select (select count(*) from collections where name ilike '%qa-ea36%') + (select count(*) from folders where name ilike '%qa-ea36%') + (select count(*) from documents where name ilike '%qa-ea36%') + (select count(*) from document_chunks where text ilike '%qa-ea36%')",
);
const orphans = sql(
  "select count(*) from chunk_embeddings e left join document_chunks c on c.id = e.chunk_id where c.id is null",
);
const lines = counts.split("\n").sort();
console.log(lines.join("\n"));
console.error(`marker rows=${marker} orphan vectors=${orphans}`);

let bad = marker !== "0" || orphans !== "0";
const before = process.argv[2];
if (before) {
  const saved = fs.readFileSync(before, "utf8").trim().split(/\r?\n/).sort();
  if (saved.join("\n") !== lines.join("\n")) {
    console.error(`row counts differ from ${before}`);
    bad = true;
  }
}
process.exit(bad ? 1 : 0);
