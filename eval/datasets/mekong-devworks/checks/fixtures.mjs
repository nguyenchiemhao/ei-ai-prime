// Shared fixtures of the validator unit tests: a tiny valid data set that each test breaks in one place.
import assert from "node:assert/strict";
import { validateDataset } from "../tools/validate.mjs";
import { buildScriptsCsv } from "../tools/build-scripts-csv.mjs";
import { DEFAULT_CONFIG } from "../tools/schema.mjs";

export const CONFIG = {
  ...DEFAULT_CONFIG,
  scriptCount: 4,
  minPairs: 2,
  requiredPairs: [
    ["leave-request", "leave-cancel"],
    ["ot-weekday", "ot-public-holiday"],
  ],
  requiredTitles: ["How to request leave"],
  groups: { A: 2, B: 1, C: 2, D: 1, E: 1, F: 1, G: 1, H: 1 },
  minGroupAPerScript: 0,
  minGroupCPerPairMember: 0,
  minGroupBScripts: 0,
  minTaskQuestions: 0,
  minDataQuestions: 0,
  minHKinds: { phone: 0, email: 0, national_id: 0 },
};

export function script(id, title, partner, extra = {}) {
  return {
    id,
    title,
    set: "HR quick answers",
    questions_en: [`${id} english one`, `${id} english two`, `${id} english three`],
    questions_vi: [`${id} tiếng việt một`, `${id} tiếng việt hai`, `${id} tiếng việt ba`],
    answer_en: `Answer for ${id}, {name}.`,
    answer_vi: `Trả lời cho ${id}, {name}.`,
    mode: "verbatim",
    action_type: "",
    action_value: "",
    status: "active",
    start_date: "",
    end_date: "",
    near_duplicate_of: partner,
    ...extra,
  };
}

export function question(n, group, language, type, correct_script, text, extra = {}) {
  return {
    id: `q-${String(n).padStart(4, "0")}`,
    group,
    language,
    history: [],
    question: text,
    type,
    correct_script,
    source: "llm-draft",
    ...extra,
  };
}

export function baseScripts() {
  return [
    script("leave-request", "How to request leave", "leave-cancel"),
    script("leave-cancel", "How to cancel a leave request", "leave-request"),
    script("ot-weekday", "OT policy on weekdays", "ot-public-holiday"),
    script("ot-public-holiday", "OT policy on public holidays", "ot-weekday"),
  ];
}

export function baseQuestions() {
  return [
    question(1, "A", "en", "information", "leave-request", "Where do I file a day off?"),
    question(2, "A", "vi", "information", "leave-cancel", "Mình muốn rút đơn nghỉ đã gửi"),
    question(3, "B", "vi", "information", "leave-request", "cach xin nghi phep nhanh"),
    question(4, "C", "en", "information", "ot-public-holiday", "Is Tet overtime paid more than normal?"),
    question(5, "C", "vi", "task", "leave-cancel", "Hủy giúp mình đơn nghỉ ngày mai"),
    question(6, "D", "en", "information", "NONE", "How many days is marriage leave?"),
    question(7, "E", "en", "out_of_scope", "NONE", "Write a Python script to sort a list"),
    question(8, "F", "vi", "greeting", "NONE", "Xin chào"),
    question(9, "G", "en", "follow_up", "NONE", "and who approves that?", {
      history: [{ user: "How does overtime work?", assistant: "Overtime needs approval." }],
    }),
    question(10, "H", "vi", "information", "leave-cancel", "Mình là An Do, SĐT 0912 345 678, muốn hủy đơn nghỉ"),
  ];
}

export const REGISTRY = {
  phones: ["0912 345 678"],
  emails: [],
  national_ids: ["079203001234"],
  names: ["An Do"],
};

export function records(values) {
  return values.map((value, i) => ({ line: i + 1, value }));
}

export function run(mutate = () => {}, config = CONFIG) {
  const data = { scripts: baseScripts(), questions: baseQuestions(), registry: structuredClone(REGISTRY) };
  mutate(data);
  let csvText = data.csvText;
  if (csvText === undefined) {
    try {
      csvText = buildScriptsCsv(data.scripts);
    } catch {
      csvText = ""; // a deliberately incomplete script cannot be exported
    }
  }
  return validateDataset(
    { scripts: records(data.scripts), questions: records(data.questions), csvText, registry: data.registry },
    config,
  );
}

export function rules(result) {
  return result.errors.map((e) => e.rule);
}

export function assertRejects(result, rule, file) {
  const hit = result.errors.find((e) => e.rule === rule && (!file || e.file === file));
  assert.ok(hit, `expected rule ${rule}, got: ${JSON.stringify(result.errors.map((e) => `${e.file}:${e.line} ${e.rule} ${e.message}`))}`);
  return hit;
}
