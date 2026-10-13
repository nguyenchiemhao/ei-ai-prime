// EA-85 (DSN-01) AC1, AC2, AC5, AC6: structural and content checks of the design canvas files
// (artboards `*.dc.html` + `canvas.json`), of docs/design/design-decisions.md and of the canvas review.
// These tests make sure no required element is missing and that the files keep the artboard format;
// how the boards look is checked by the reviewer on the published canvas (claude.ai).
//
// Run (mirror in the repo):      node --test docs/design/checks/canvas.test.mjs
// Run (working copy of a run):   CANVAS_DIR=.work/EA-85/canvas/project node --test docs/design/checks/canvas.test.mjs
// (Node 22: pass the file path; `node --test <directory>` does not work.) No network, no dependencies.

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const DIR = path.resolve(ROOT, process.env.CANVAS_DIR || "docs/design/canvas");
const DECISIONS = path.join(ROOT, "docs/design/design-decisions.md");
const REVIEW = path.join(ROOT, "docs/design/reviews/2026-10-13-canvas-review.md");

const REVIEW_HEADINGS = [
  "1. Scope and method",
  "2. Summary",
  "3. Findings",
  "4. Console Chat deep-dive",
  "5. Decision coverage",
  "6. Changes in this revision",
  "7. Decisions for the owner",
  "8. Follow-ups",
];
const SEVERITIES = ["Blocker", "High", "Medium", "Low", "Info"];
const DECISION_STATUS = ["Decided", "Proposed — owner to confirm"];
const EXPECTED_X = Array.from({ length: 20 }, (_, i) => `X${i + 1}`);

const cache = new Map();
const read = (file) => (cache.has(file) ? cache.get(file) : cache.set(file, fs.readFileSync(file, "utf8")).get(file));
const exists = (file) => fs.existsSync(file);
const artboardFiles = () => fs.readdirSync(DIR).filter((f) => f.endsWith(".dc.html")).sort();
const board = (name) => read(path.join(DIR, `${name}.dc.html`));
const canvas = () => JSON.parse(read(path.join(DIR, "canvas.json")));
const decodeAttr = (s) => s.replace(/&#39;/g, "'").replace(/&amp;/g, "&");
const dataProps = (html) => {
  const m = html.match(/<script type="text\/x-dc" data-dc-script data-props='([^']*)'>/);
  return m ? JSON.parse(decodeAttr(m[1])) : null;
};
const lineWith = (html, needle) => html.split("\n").find((l) => l.includes(needle));
const mustContain = (html, needles, label) => {
  for (const n of needles) assert.ok(html.includes(n), `${label} must contain: ${n}`);
};
const tableRows = (md, startPattern) => {
  const lines = md.split("\n");
  const start = lines.findIndex((l) => startPattern.test(l));
  assert.ok(start >= 0, `table header not found: ${startPattern}`);
  const rows = [];
  for (let i = start + 2; i < lines.length && lines[i].startsWith("|"); i++) {
    rows.push(lines[i].split("|").slice(1, -1).map((c) => c.trim()));
  }
  return rows;
};
const section = (md, headingPattern) => {
  const m = md.match(new RegExp(`^## ${headingPattern}[^\\n]*\\n([\\s\\S]*?)(?=^## |(?![\\s\\S]))`, "m"));
  assert.ok(m, `section not found: ${headingPattern}`);
  return m[1];
};

// ---------- Structural tests (S1-S8): pass on the unchanged baseline ----------

test("S1 canvas_json_boards_order_and_files_match", () => {
  const c = canvas();
  const files = artboardFiles();
  const boards = Object.keys(c.boards).sort();
  assert.deepEqual(boards, files, "boards in canvas.json must equal the *.dc.html files");
  assert.equal(new Set(c.order).size, c.order.length, "order has duplicates");
  assert.deepEqual([...c.order].sort(), files, "order must list every file once");
});

test("S2 every_artboard_keeps_the_dc_format", () => {
  for (const f of artboardFiles()) {
    const html = read(path.join(DIR, f));
    assert.ok(html.startsWith("<!doctype html>"), `${f}: doctype`);
    assert.match(html, /<html lang="(en|vi)">/, `${f}: html lang`);
    assert.match(html, /<title>[^<]+<\/title>/, `${f}: title`);
    const head = html.slice(html.indexOf("<head>"), html.indexOf("</head>"));
    assert.ok(head.split("\n").includes('<script src="./support.js"></script>'), `${f}: support.js line in head`);
    assert.ok(html.includes("<x-dc>") && html.includes("</x-dc>"), `${f}: x-dc block`);
    const props = dataProps(html);
    assert.ok(props, `${f}: dc-script block with parseable data-props`);
    assert.ok(html.includes("class Component extends DCLogic"), `${f}: Component class`);
  }
});

test("S3 preview_size_equals_board_size", () => {
  const c = canvas();
  for (const [f, b] of Object.entries(c.boards)) {
    const p = dataProps(read(path.join(DIR, f)))["$preview"];
    assert.ok(p, `${f}: $preview`);
    assert.deepEqual({ w: p.width, h: p.height }, { w: b.w, h: b.h }, `${f}: $preview vs canvas.json`);
  }
});

test("S4 no_emoji_or_iframes", () => {
  for (const f of artboardFiles()) {
    const html = read(path.join(DIR, f));
    assert.ok(!/\p{Extended_Pictographic}/u.test(html), `${f}: emoji`);
    assert.ok(!html.includes("️"), `${f}: variation selector`);
    assert.ok(!/<iframe/i.test(html), `${f}: iframe`);
  }
});

test("S5 links_and_imports_resolve", () => {
  const files = new Set(artboardFiles());
  for (const f of artboardFiles()) {
    const html = read(path.join(DIR, f));
    for (const m of html.matchAll(/href="([A-Za-z]+\.dc\.html)(#[^"]*)?"/g)) assert.ok(files.has(m[1]), `${f}: broken link ${m[1]}`);
    for (const m of html.matchAll(/<dc-import name="([A-Za-z]+)"/g)) assert.ok(files.has(`${m[1]}.dc.html`), `${f}: broken import ${m[1]}`);
  }
});

test("S6 boards_do_not_overlap", () => {
  const entries = Object.entries(canvas().boards);
  for (let i = 0; i < entries.length; i++) {
    for (let j = i + 1; j < entries.length; j++) {
      const [na, a] = entries[i];
      const [nb, b] = entries[j];
      const overlap = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
      assert.ok(!overlap, `${na} overlaps ${nb}`);
    }
  }
});

test("S7 icon_only_buttons_have_aria_label", () => {
  for (const f of artboardFiles()) {
    const html = read(path.join(DIR, f));
    for (const m of html.matchAll(/<(button|a)\b([^>]*)>([\s\S]*?)<\/\1>/g)) {
      const text = m[3].replace(/<svg[\s\S]*?<\/svg>/g, "").replace(/<[^>]+>/g, "").replace(/\{\{[^}]*\}\}/g, "x").trim();
      if (text === "") assert.ok(/aria-label="[^"]+"/.test(m[2]), `${f}: icon-only <${m[1]}> without aria-label: ${m[0].slice(0, 90)}`);
    }
  }
});

test("S8 form_fields_use_the_field_border (X17)", () => {
  for (const f of artboardFiles()) {
    const html = read(path.join(DIR, f));
    for (const m of html.matchAll(/<(input|select|textarea)\b[^>]*>/g)) {
      if (m[1] === "input" && /type="(checkbox|radio)"/.test(m[0])) continue;
      assert.ok(!/#C9CED4/i.test(m[0]), `${f}: field still uses #C9CED4: ${m[0].slice(0, 80)}`);
    }
    for (const m of html.matchAll(/<form\b[^>]*>/g)) assert.ok(!/#C9CED4/i.test(m[0]), `${f}: composer frame still uses #C9CED4`);
  }
});

// ---------- AC1: map ----------

test("AC1: every board is listed in the design-decisions.md artboard table and every listed name has a file", () => {
  const rows = tableRows(read(DECISIONS), /^\| Artboard \| Màn hình/);
  const listed = [];
  for (const [first] of rows) {
    if (first === "—") continue;
    for (const part of first.split(" · ")) {
      const name = part.replace(/\(.*?\)/g, "").replace(/\*/g, "").trim();
      assert.match(name, /^[A-Za-z]+$/, `artboard name not parseable: ${part}`);
      listed.push(name);
    }
  }
  assert.equal(new Set(listed).size, listed.length, "an artboard is listed twice");
  const files = artboardFiles().map((f) => f.replace(".dc.html", "")).sort();
  assert.deepEqual([...listed].sort(), files);
});

// ---------- AC2: discrepancies ----------

test("AC2: X1–X20 each have a decision row", () => {
  const md = section(read(DECISIONS), "6\\.");
  const rows = tableRows(md, /^\| # \| Discrepancy \/ question \| Decision \| Status \| Applied in \|/);
  assert.deepEqual(rows.map((r) => r[0]), EXPECTED_X);
  for (const r of rows) {
    assert.equal(r.length, 5, `${r[0]}: 5 columns`);
    assert.ok(r[1].length > 10, `${r[0]}: discrepancy text`);
    assert.ok(r[2].length > 10, `${r[0]}: decision text`);
    assert.ok(DECISION_STATUS.includes(r[3]), `${r[0]}: status "${r[3]}"`);
    assert.ok(r[4].length > 2, `${r[0]}: applied in`);
  }
});

test("AC2: canvas matches the decisions (X1, X3, X4, X5, X6, X13, X14, X15)", () => {
  assert.ok(lineWith(board("CollectionDetail"), "Business Travel Policy (old).doc").includes("Later"), "X1: .doc row carries a Later tag");
  const appearance = board("ChannelAppearance");
  assert.ok(appearance.includes("5.1:1") && !appearance.includes("5.3:1"), "X3: contrast 5.1:1");
  assert.ok(lineWith(board("Unanswered"), "Fix them by adding a document").includes("Later"), "X4: similarity grouping carries a Later tag");
  const settings = board("ChannelSettings");
  assert.ok(settings.includes("10 for anonymous"), "X5: rate default text");
  assert.ok(!lineWith(settings, "Send transcript to").includes("Later"), "X6: transcript email is in the prototype");
  assert.ok(settings.includes("hr@mekongdevworks.example"), "X6: HR email");
  assert.ok(lineWith(settings, "Webhook URL").includes("Later"), "X6: webhook keeps the Later tag");
  assert.ok(!board("OrgSettings").includes("local models take over"), "X13: no local fallback text");
  assert.ok(board("Conversations").includes("Search first questions"), "X14: search scope");
  assert.ok(board("AssistantInstructions").includes("apply immediately"), "X15: immediate effect");
});

// ---------- AC5: WGT-11 ----------

test("AC5: WidgetHandoff draws the confirmation and the daily limit, and WidgetNotFound links to it", () => {
  const f = path.join(DIR, "WidgetHandoff.dc.html");
  assert.ok(exists(f), "WidgetHandoff.dc.html exists");
  mustContain(read(f), ['role="dialog"', 'aria-modal="true"', "Gửi tới HR", "Hủy", "3 lần hôm nay", '<html lang="vi">'], "WidgetHandoff");
  assert.ok(board("WidgetNotFound").includes('href="WidgetHandoff.dc.html"'), "WidgetNotFound links to WidgetHandoff");
});

// ---------- AC6: Console Chat (D67) ----------

test("AC6: Chat shows the five chat elements", () => {
  const html = board("Chat");
  mustContain(html, [
    "New chat", "Search chats", "Today", "Yesterday", "Previous 7 days", "Live v7", "Answering as Minh Pham",
    "Searched 2 collections", "Checked HR System", "Sources", 'href="PlaygroundFromChat.dc.html"', "Selected",
  ], "Chat");
  assert.ok(!html.includes('href="Playground.dc.html"'), "the header link to the Playground is replaced by the per-answer action");
  const cites = [...html.matchAll(/<a\b[^>]*href="#c\d"[^>]*>/g)].map((m) => m[0]);
  assert.ok(cites.length >= 3, "citation links exist");
  for (const c of cites) assert.ok(c.includes('aria-label="Source '), `citation without accessible name: ${c.slice(0, 80)}`);
});

test("AC6: ChatStates covers every state", () => {
  const f = path.join(DIR, "ChatStates.dc.html");
  assert.ok(exists(f), "ChatStates.dc.html exists");
  const html = read(f);
  mustContain(html, ["New chat", "Assistant picker", "Streaming", "Not found", "Maintenance", "Rate limit", "System busy", "No assistant", "History search", 'aria-label="Stop answer"', 'role="listbox"', 'aria-live="polite"'], "ChatStates");
});

test("AC6: ChatMember is the Member view", () => {
  const f = path.join(DIR, "ChatMember.dc.html");
  assert.ok(exists(f), "ChatMember.dc.html exists");
  const html = read(f);
  assert.match(html, /<html lang="vi">/);
  assert.match(html, /<dc-import name="Sidebar"[^>]*role="member"/);
  mustContain(html, ["An Do · all-staff, project-falcon", "chỉ dữ liệu của bạn"], "ChatMember");
  assert.ok(!html.includes("Playground"), "Members never see the Playground");
});

test("AC6: Sidebar has a Member variant", () => {
  const props = dataProps(board("Sidebar"));
  assert.ok(props.role && props.role.options.includes("member"), "role enum has member");
  assert.ok(props.lang && props.lang.options.includes("vi"), "lang enum has vi");
});

test("AC6: Members shows the D67 fields", () => {
  const html = board("Members");
  mustContain(html, ["Knowledge groups", "External user ID", "emp-0421", "Never shown to the AI model", ">Member<", "Chat (use assistants)", "Playground (test drafts, see traces)"], "Members");
});

test("AC6: ChannelSettings and ChannelConsoleChat show the built-in channel", () => {
  const settings = board("ChannelSettings");
  mustContain(settings, ["Console chat", "Built-in", 'href="ChannelConsoleChat.dc.html"'], "ChannelSettings");
  const f = path.join(DIR, "ChannelConsoleChat.dc.html");
  assert.ok(exists(f), "ChannelConsoleChat.dc.html exists");
  mustContain(read(f), ["cannot be deleted", "Greeting", "Members &amp; roles"], "ChannelConsoleChat");
});

test("AC6: AssistantConfig has the Console chat switch", () => {
  mustContain(board("AssistantConfig"), ["Available in Console chat", 'role="switch"', "Who can use it", 'id="console-chat"'], "AssistantConfig");
});

test("AC6: Conversations, OrgSettings and PlaygroundFromChat", () => {
  mustContain(board("Conversations"), ["Console chat", "rates an answer"], "Conversations");
  mustContain(board("OrgSettings"), ["Console chat"], "OrgSettings");
  const f = path.join(DIR, "PlaygroundFromChat.dc.html");
  assert.ok(exists(f), "PlaygroundFromChat.dc.html exists");
  mustContain(read(f), ["Opened from Chat", 'href="Chat.dc.html"'], "PlaygroundFromChat");
});

// ---------- Review document ----------

test("Review: canvas review is complete", () => {
  assert.ok(exists(REVIEW), "review file exists");
  const md = read(REVIEW);
  for (const h of REVIEW_HEADINGS) assert.match(md, new RegExp(`^## ${h.replace(/[.]/g, "\\.")}\\s*$`, "m"), `heading: ${h}`);
  const rows = md.split("\n").filter((l) => /^\| (CH|GL)-/.test(l)).map((l) => l.split("|").slice(1, -1).map((c) => c.trim()));
  assert.ok(rows.length >= 30, "at least 30 findings");
  const ids = new Set();
  for (const r of rows) {
    assert.match(r[0], /^(CH|GL)-\d{2}$/, `finding id ${r[0]}`);
    assert.ok(!ids.has(r[0]), `duplicate finding id ${r[0]}`);
    ids.add(r[0]);
    assert.equal(r.length, 7, `${r[0]}: 7 columns`);
    assert.ok(SEVERITIES.includes(r[1]), `${r[0]}: severity "${r[1]}"`);
    assert.ok(r[4].length > 10 && r[5].length > 10, `${r[0]}: finding and recommendation`);
    assert.ok(r[6].length > 0, `${r[0]}: status`);
  }
});
