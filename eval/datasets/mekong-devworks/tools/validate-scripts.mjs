// Validation of scripts.jsonl and scripts.csv (AC1, AC3, AC6).
import { normalise, extractUrls, extractVariables } from "./text.mjs";
import { isReservedEmail, isReservedUrl, checkPersonalData } from "./personal-data.mjs";
import { parseCsv } from "./csv.mjs";
import { buildScriptsCsv } from "./build-scripts-csv.mjs";

const FILE = "scripts.jsonl";
const CSV_FILE = "scripts.csv";
const TEXT_FIELDS = ["id", "title", "set", "answer_en", "answer_vi", "mode", "action_type", "action_value", "status", "start_date", "end_date"];
const EXAMPLE_FIELDS = ["questions_en", "questions_vi"];

const err = (line, rule, message, file = FILE) => ({ file, line, rule, message });

function isIsoDate(s) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const d = new Date(`${s}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s;
}

function hasAllFields(s, line, errors) {
  const missing = [...TEXT_FIELDS, ...EXAMPLE_FIELDS].filter((f) => s[f] === undefined || s[f] === null);
  if (missing.length) errors.push(err(line, "script-field", `missing field(s): ${missing.join(", ")}`));
  return missing.length === 0;
}

function checkExamples(s, line, config, seen, errors) {
  const [min, max] = config.examplesPerLanguage;
  for (const field of EXAMPLE_FIELDS) {
    const list = s[field];
    if (!Array.isArray(list) || list.length < min || list.length > max || list.some((q) => typeof q !== "string" || q.trim() === "")) {
      errors.push(err(line, "script-examples", `${s.id}.${field} must hold ${min}-${max} non-empty strings`));
      continue;
    }
    for (const q of list) {
      if (q.includes("|")) errors.push(err(line, "script-examples", `${s.id}.${field} example contains "|": ${q}`));
      const key = normalise(q);
      if (seen.has(key)) errors.push(err(line, "script-example-duplicate", `${s.id}.${field} example "${q}" repeats an example of ${seen.get(key)}`));
      else seen.set(key, `${s.id}.${field}`);
    }
  }
}

function checkAction(s, line, config, errors) {
  if (!config.modes.includes(s.mode)) {
    errors.push(err(line, "script-mode", `${s.id}: mode "${s.mode}" is not one of ${config.modes.join("/")}`));
    return;
  }
  if (s.mode !== "action") {
    if (s.action_type !== "" || s.action_value !== "") errors.push(err(line, "script-action", `${s.id}: action_type/action_value must be empty unless mode is action`));
    return;
  }
  if (!config.actionTypes.includes(s.action_type)) errors.push(err(line, "script-action", `${s.id}: action_type "${s.action_type}" is not valid`));
  else if (s.action_type === "link" && !(/^https:\/\//.test(s.action_value) && isReservedUrl(s.action_value))) {
    errors.push(err(line, "script-action", `${s.id}: link action needs an https URL on a *.example host`));
  } else if (s.action_type === "handoff" && !isReservedEmail(s.action_value)) {
    errors.push(err(line, "script-action", `${s.id}: handoff action needs an email on a reserved domain`));
  }
}

function checkStatusAndDates(s, line, config, errors) {
  if (!config.statuses.includes(s.status)) errors.push(err(line, "script-status", `${s.id}: status "${s.status}" is not one of ${config.statuses.join("/")}`));
  for (const f of ["start_date", "end_date"]) {
    if (s[f] !== "" && !isIsoDate(s[f])) errors.push(err(line, "script-date", `${s.id}: ${f} "${s[f]}" is not an ISO date`));
  }
  if (isIsoDate(s.start_date) && isIsoDate(s.end_date) && s.start_date > s.end_date) {
    errors.push(err(line, "script-date", `${s.id}: start_date is after end_date`));
  }
}

function checkContent(s, line, config, registry, errors) {
  for (const field of ["answer_en", "answer_vi"]) {
    if (typeof s[field] !== "string" || s[field].trim() === "") errors.push(err(line, "script-answer", `${s.id}: ${field} is empty`));
    for (const v of extractVariables(String(s[field]))) {
      if (!config.variables.includes(v)) errors.push(err(line, "script-variable", `${s.id}: ${field} uses unknown variable {${v}}`));
    }
  }
  const texts = [...TEXT_FIELDS.map((f) => s[f]), ...EXAMPLE_FIELDS.flatMap((f) => s[f])].filter((t) => typeof t === "string");
  for (const t of texts) {
    if (/^[=+\-@]/.test(t)) errors.push(err(line, "script-injection", `${s.id}: a field starts with a formula character: ${t.slice(0, 30)}`));
    if (/\b(TODO|TBD)\b/.test(t)) errors.push(err(line, "script-placeholder", `${s.id}: placeholder text found: ${t.slice(0, 30)}`));
    for (const url of extractUrls(t)) {
      if (!isReservedUrl(url)) errors.push(err(line, "script-url", `${s.id}: URL ${url} is not on a *.example host`));
    }
  }
  for (const t of [s.answer_en, s.answer_vi, ...EXAMPLE_FIELDS.flatMap((f) => s[f])].filter((x) => typeof x === "string")) {
    for (const m of checkPersonalData(t, registry)) errors.push(err(line, "script-personal-data", `${s.id}: ${m}`));
  }
}

function checkPairs(entries, config, errors) {
  const byId = new Map(entries.map(({ value }) => [value.id, value]));
  let linked = 0;
  for (const { line, value: s } of entries) {
    if (s.near_duplicate_of === undefined) continue;
    const partner = byId.get(s.near_duplicate_of);
    if (!partner || partner.id === s.id || partner.near_duplicate_of !== s.id) {
      errors.push(err(line, "script-pair", `${s.id}: near_duplicate_of "${s.near_duplicate_of}" is missing, itself, or not symmetric`));
    } else linked++;
  }
  const pairs = linked / 2;
  if (pairs < config.minPairs) errors.push(err(0, "script-pairs-min", `only ${pairs} near-duplicate pairs, need at least ${config.minPairs}`));
  for (const [a, b] of config.requiredPairs) {
    if (byId.get(a)?.near_duplicate_of !== b || byId.get(b)?.near_duplicate_of !== a) {
      errors.push(err(0, "script-required-pair", `required design pair ${a} / ${b} is missing`));
    }
  }
  return pairs;
}

export function validateScripts(entries, registry, config) {
  const errors = [];
  const seenIds = new Set();
  const seenTitles = new Set();
  const seenExamples = new Map();
  for (const { line, value: s } of entries) {
    if (!hasAllFields(s, line, errors)) continue;
    if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(s.id) || seenIds.has(s.id)) errors.push(err(line, "script-id", `id "${s.id}" is not kebab-case or not unique`));
    seenIds.add(s.id);
    if (s.title.trim() === "" || seenTitles.has(s.title)) errors.push(err(line, "script-title", `${s.id}: title is empty or not unique`));
    seenTitles.add(s.title);
    if (!config.sets.includes(s.set)) errors.push(err(line, "script-set", `${s.id}: set "${s.set}" is not one of ${config.sets.join(", ")}`));
    checkExamples(s, line, config, seenExamples, errors);
    checkAction(s, line, config, errors);
    checkStatusAndDates(s, line, config, errors);
    checkContent(s, line, config, registry, errors);
  }
  if (entries.length !== config.scriptCount) errors.push(err(0, "script-count", `${entries.length} scripts, expected ${config.scriptCount}`));
  const titles = new Set(entries.map((e) => e.value.title));
  for (const t of config.requiredTitles) {
    if (!titles.has(t)) errors.push(err(0, "script-required-title", `design title "${t}" is missing`));
  }
  const pairs = checkPairs(entries, config, errors);
  return { errors, pairs };
}

const isBuildable = (s) => EXAMPLE_FIELDS.every((f) => Array.isArray(s[f])) && TEXT_FIELDS.every((f) => typeof s[f] === "string");

export function validateCsv(csvText, entries, config) {
  const errors = [];
  const normalised = String(csvText ?? "").replace(/\r\n/g, "\n");
  const { header, rows } = parseCsv(normalised);
  if (header.join(",") !== config.csvColumns.join(",")) {
    errors.push(err(1, "csv-header", `header must be ${config.csvColumns.join(",")}`, CSV_FILE));
    return errors;
  }
  if (rows.length !== entries.length) {
    errors.push(err(0, "csv-rows", `${rows.length} rows, scripts.jsonl has ${entries.length} scripts`, CSV_FILE));
    return errors;
  }
  if (!entries.every((e) => isBuildable(e.value))) return errors; // script-field already reports the incomplete script
  const expected = buildScriptsCsv(entries.map((e) => e.value));
  if (normalised !== expected) {
    const want = parseCsv(expected).rows;
    const bad = rows.findIndex((r, i) => JSON.stringify(r) !== JSON.stringify(want[i]));
    errors.push(err(bad + 2, "csv-content", "scripts.csv differs from scripts.jsonl; regenerate it with tools/build-scripts-csv.mjs", CSV_FILE));
  }
  return errors;
}
