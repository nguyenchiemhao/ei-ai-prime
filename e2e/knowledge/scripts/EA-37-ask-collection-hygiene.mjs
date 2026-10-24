// EA-37 (KB-06): test data hygiene check for the "Ask this collection" QA run (SQL, read only).
//   node e2e/knowledge/scripts/EA-37-ask-collection-hygiene.mjs            prints the row count of EVERY base table
//   node e2e/knowledge/scripts/EA-37-ask-collection-hygiene.mjs <before.txt>
//       also compares with a file saved from an earlier run of this script (`... > before.txt`)
// Exit 1 when a row carries the marker `qa-ea37`, a vector has no chunk (orphan), or the counts differ from the file.
// Needs the stack up (`docker compose ps db`). It never writes to the database.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

function sql(query) {
  const result = spawnSync(
    "docker",
    ["compose", "exec", "-T", "db", "psql", "-U", "postgres", "-d", "ei_ai", "-tA", "-c", query],
    { cwd: ROOT, encoding: "utf8" },
  );
  if (result.status !== 0) throw new Error(`psql failed: ${result.stderr}`);
  return result.stdout.trim();
}

const counts = sql(
  `select table_name || '=' || (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from public.%I', table_name), false, true, '')))[1]::text
     from information_schema.tables where table_schema = 'public' and table_type = 'BASE TABLE' order by 1`,
);
const marker = sql(
  "select (select count(*) from collections where name ilike '%qa-ea37%') + (select count(*) from folders where name ilike '%qa-ea37%') + (select count(*) from documents where name ilike '%qa-ea37%') + (select count(*) from document_chunks where text ilike '%qa-ea37%')",
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
