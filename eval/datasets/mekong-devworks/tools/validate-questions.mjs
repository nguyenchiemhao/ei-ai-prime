// Validation of test_questions.jsonl (AC2, AC3, AC4, AC6).
import { normalise, hasVietnameseDiacritics, extractUrls } from "./text.mjs";
import { extractPersonalData, checkPersonalData, digitsOf, isVietnamesePhone, isCccd, isCmnd, isReservedUrl } from "./personal-data.mjs";

const FILE = "test_questions.jsonl";
const err = (line, rule, message) => ({ file: FILE, line, rule, message });

function historyProblem(history) {
  if (!Array.isArray(history)) return "history must be an array";
  if (history.length > 2) return "history may hold at most 2 turns";
  const bad = history.find((t) => !t || typeof t.user !== "string" || t.user === "" || typeof t.assistant !== "string" || t.assistant === "");
  return bad === undefined ? null : "every history turn needs non-empty user and assistant strings";
}

function checkRecord(q, line, config, scriptsById, errors) {
  const missing = config.requiredQuestionFields.filter((f) => q[f] === undefined || q[f] === null || (f !== "history" && q[f] === ""));
  if (missing.length) {
    errors.push(err(line, "question-field", `missing field(s): ${missing.join(", ")}`));
    return false;
  }
  const notStrings = ["id", "group", "language", "type", "correct_script", "question"].filter((f) => typeof q[f] !== "string");
  if (notStrings.length) {
    errors.push(err(line, "question-type", `field(s) must be strings: ${notStrings.join(", ")}`));
    return false;
  }
  if (!/^q-\d{4}$/.test(q.id)) errors.push(err(line, "question-id", `id "${q.id}" must look like q-0001`));
  if (!(q.group in config.groups)) errors.push(err(line, "question-enum", `group "${q.group}" is not one of ${Object.keys(config.groups).join("")}`));
  if (!config.languages.includes(q.language)) errors.push(err(line, "question-enum", `language "${q.language}" is not one of ${config.languages.join("/")}`));
  if (!config.types.includes(q.type)) errors.push(err(line, "question-enum", `type "${q.type}" is not an allowed type`));
  if (q.source !== undefined && !config.sources.includes(q.source)) errors.push(err(line, "question-source", `source "${q.source}" is not one of ${config.sources.join("/")}`));
  const problem = historyProblem(q.history);
  if (problem) errors.push(err(line, "question-history", problem));
  if (q.correct_script !== "NONE" && !scriptsById.has(q.correct_script)) {
    errors.push(err(line, "question-script", `correct_script "${q.correct_script}" does not exist`));
    return false;
  }
  return true;
}

function checkGroupRule(q, line, config, scriptsById, errors) {
  const rule = config.groupRules[q.group];
  if (!rule || !config.types.includes(q.type) || historyProblem(q.history)) return;
  const bad = (msg) => errors.push(err(line, "question-group-rule", `${q.id} (group ${q.group}): ${msg}`));
  if (rule.script === "NONE" && q.correct_script !== "NONE") bad(`correct_script must be NONE, got ${q.correct_script}`);
  if (rule.script === "id" && q.correct_script === "NONE") bad("correct_script must be a script id, got NONE");
  if (!rule.types.includes(q.type)) bad(`type "${q.type}" is not allowed (${rule.types.join("/")})`);
  const [minTurns, maxTurns] = rule.history ?? [0, 0];
  if (q.history.length < minTurns || q.history.length > maxTurns) bad(`history must hold ${minTurns}-${maxTurns} turns, has ${q.history.length}`);
  if (rule.needsPair && q.correct_script !== "NONE" && !scriptsById.get(q.correct_script)?.near_duplicate_of) {
    bad(`${q.correct_script} has no near-duplicate partner`);
  }
}

function checkLanguage(q, line, errors) {
  if (q.group === "B") {
    if (q.language !== "vi") errors.push(err(line, "group-b-language", `${q.id}: group B must be Vietnamese`));
    if (hasVietnameseDiacritics(q.question)) errors.push(err(line, "group-b-accent", `${q.id}: group B must be unaccented`));
  } else if (q.language === "vi" && !hasVietnameseDiacritics(q.question)) {
    errors.push(err(line, "language-accent", `${q.id}: Vietnamese questions outside group B need diacritics`));
  }
}

function textsOf(q) {
  const turns = q.history.filter((t) => t && typeof t === "object");
  return [q.question, ...turns.flatMap((t) => [t.user, t.assistant])].filter((t) => typeof t === "string");
}

function checkPersonal(q, line, registry, errors) {
  for (const t of textsOf(q)) {
    if (/^[=+\-@]/.test(t)) errors.push(err(line, "question-injection", `${q.id}: a text starts with a formula character (CSV injection): ${t.slice(0, 3)}...`));
    for (const m of checkPersonalData(t, registry)) errors.push(err(line, "personal-data", `${q.id}: ${m}`));
    for (const url of extractUrls(t)) {
      if (!isReservedUrl(url)) errors.push(err(line, "personal-data", `${q.id}: URL ${url} is not on a *.example host`));
    }
  }
}

function kindsOf(text, registry) {
  const { emails, numbers, employeeCodes } = extractPersonalData(text);
  const digits = numbers.map(digitsOf);
  return {
    phone: numbers.some(isVietnamesePhone),
    email: emails.length > 0,
    national_id: digits.some((d) => isCccd(d) || isCmnd(d)),
    any: emails.length + numbers.length + employeeCodes.length > 0 || (registry.names || []).some((n) => text.includes(n)),
  };
}

function checkGroupH(records, config, registry, errors) {
  const found = { phone: 0, email: 0, national_id: 0 };
  for (const { line, value: q } of records) {
    if (q.group !== "H" || typeof q.question !== "string") continue;
    const kinds = kindsOf(q.question, registry);
    if (!kinds.any) errors.push(err(line, "group-h-data", `${q.id}: group H questions must contain fake personal data`));
    for (const k of Object.keys(found)) if (kinds[k]) found[k]++;
  }
  for (const [kind, min] of Object.entries(config.minHKinds)) {
    if (found[kind] < min) errors.push(err(0, "group-h-kinds", `group H needs at least ${min} questions with ${kind.replace("_", " ")}, found ${found[kind]}`));
  }
}

function checkCounts(stats, config, errors) {
  for (const [group, target] of Object.entries(config.groups)) {
    const count = stats.byGroup[group] ?? 0;
    if (Math.abs(count - target) > config.groupTolerance * target + 1e-9) {
      errors.push(err(0, "group-count", `group ${group} has ${count} questions, target ${target} (+-${config.groupTolerance * 100}%)`));
    }
  }
  const [lo, hi] = config.languageShare;
  for (const lang of config.languages) {
    const share = stats.questions ? (stats.byLanguage[lang] ?? 0) / stats.questions : 0;
    if (share < lo - 1e-9 || share > hi + 1e-9) errors.push(err(0, "language-share", `${lang} share is ${(share * 100).toFixed(1)}%, allowed ${Math.round(lo * 100)}-${Math.round(hi * 100)}%`));
  }
}

function checkCoverage(records, scripts, config, errors) {
  const countBy = (pred, key) => {
    const m = new Map();
    for (const { value: q } of records) if (pred(q)) m.set(q[key], (m.get(q[key]) ?? 0) + 1);
    return m;
  };
  const inA = countBy((q) => q.group === "A", "correct_script");
  const inC = countBy((q) => q.group === "C", "correct_script");
  const thin = (list, map, min) => list.filter((s) => (map.get(s.id) ?? 0) < min).map((s) => s.id);
  const testable = scripts.filter((s) => s.action_type !== "handoff");
  const lowA = thin(testable, inA, config.minGroupAPerScript);
  if (lowA.length) errors.push(err(0, "coverage", `scripts with fewer than ${config.minGroupAPerScript} group A questions: ${lowA.join(", ")}`));
  const lowC = thin(scripts.filter((s) => s.near_duplicate_of), inC, config.minGroupCPerPairMember);
  if (lowC.length) errors.push(err(0, "coverage", `pair members with fewer than ${config.minGroupCPerPairMember} group C questions: ${lowC.join(", ")}`));
  const bScripts = countBy((q) => q.group === "B", "correct_script").size;
  if (bScripts < config.minGroupBScripts) errors.push(err(0, "coverage", `group B covers ${bScripts} scripts, need ${config.minGroupBScripts}`));
  for (const [type, min] of [["task", config.minTaskQuestions], ["data", config.minDataQuestions]]) {
    const n = records.filter(({ value: q }) => q.type === type).length;
    if (n < min) errors.push(err(0, "coverage", `only ${n} ${type} questions, need ${min}`));
  }
}

export function validateQuestions(entries, scripts, registry, config) {
  const errors = [];
  const scriptsById = new Map(scripts.map((s) => [s.id, s]));
  const references = new Set();
  for (const s of scripts) {
    const texts = [s.title, ...(s.questions_en ?? []), ...(s.questions_vi ?? [])];
    for (const t of texts) if (typeof t === "string") references.add(normalise(t));
  }
  const ids = new Set();
  const seenKeys = new Map();
  const stats = { questions: entries.length, byGroup: {}, byLanguage: {}, byType: {} };
  for (const { line, value: q } of entries) {
    stats.byGroup[q.group] = (stats.byGroup[q.group] ?? 0) + 1;
    stats.byLanguage[q.language] = (stats.byLanguage[q.language] ?? 0) + 1;
    stats.byType[q.type] = (stats.byType[q.type] ?? 0) + 1;
    const complete = checkRecord(q, line, config, scriptsById, errors);
    if (q.id !== undefined && ids.has(q.id)) errors.push(err(line, "question-id", `duplicate id ${q.id}`));
    ids.add(q.id);
    if (typeof q.question !== "string" || !Array.isArray(q.history)) continue;
    if (complete) checkGroupRule(q, line, config, scriptsById, errors);
    checkLanguage(q, line, errors);
    checkPersonal(q, line, registry, errors);
    const text = normalise(q.question);
    if (references.has(text)) errors.push(err(line, "separation", `${q.id}: equals a script title or example question after normalisation`));
    const key = [text, ...q.history.map((t) => `${normalise(String(t?.user))}/${normalise(String(t?.assistant))}`)].join("|");
    if (seenKeys.has(key)) errors.push(err(line, "duplicate", `${q.id}: same question and history as line ${seenKeys.get(key)}`));
    else seenKeys.set(key, line);
  }
  checkCounts(stats, config, errors);
  checkCoverage(entries, scripts, config, errors);
  checkGroupH(entries, config, registry, errors);
  return { errors, stats };
}
