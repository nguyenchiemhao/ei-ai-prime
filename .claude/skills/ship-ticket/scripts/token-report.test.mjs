import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  collectReport,
  findProjectDir,
  findSession,
  formatReport,
  formatTokens,
  isPrompt,
  parseArgs,
  splitRounds,
  sumUsage,
} from "./token-report.mjs";

// Builds an assistant transcript line with a usage block
// Input: id (string), model (string), usage (object), timestamp (string)
// Output: object
const assistant = (id, model, usage, timestamp = "2026-10-19T10:00:00Z") => ({
  type: "assistant",
  timestamp,
  message: { id, model, usage },
});

// Builds a prompt line (a dispatch or a resume)
// Input: text (string), timestamp (string)
// Output: object
const prompt = (text, timestamp = "2026-10-19T10:00:00Z") => ({
  type: "user",
  timestamp,
  message: { role: "user", content: text },
});

// Builds a tool-result line
// Input: timestamp (string)
// Output: object
const toolResult = (timestamp = "2026-10-19T10:00:00Z") => ({
  type: "user",
  timestamp,
  message: { role: "user", content: [{ type: "tool_result", content: "ok" }] },
});

// Writes objects as a JSON Lines file
// Input: file (string), entries (object[])
// Output: void
const writeJsonl = (file, entries) => {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, entries.map((entry) => JSON.stringify(entry)).join("\n") + "\n");
};

test("token_report_tells_prompts_from_tool_results_and_meta_lines", () => {
  assert.equal(isPrompt(prompt("go")), true);
  assert.equal(isPrompt({ ...prompt("reminder"), isMeta: true }), false);
  assert.equal(isPrompt(toolResult()), false);
  assert.equal(isPrompt(assistant("m1", "claude-opus-5-5", {})), false);
});

test("token_report_splits_rounds_at_prompts_and_counts_a_streamed_message_once", () => {
  const usage = { input_tokens: 10, output_tokens: 5 };
  const rounds = splitRounds(
    [
      prompt("dispatch"),
      assistant("m1", "claude-sonnet-5-5", usage),
      assistant("m1", "claude-sonnet-5-5", usage),
      toolResult(),
      assistant("m2", "claude-sonnet-5-5", usage),
      prompt("resume with review-1.md"),
      assistant("m3", "claude-sonnet-5-5", usage),
    ],
    null,
  );

  assert.deepEqual(
    rounds.map((round) => round.length),
    [2, 1],
  );
});

test("token_report_ignores_entries_older_than_the_ticket_start", () => {
  const usage = { input_tokens: 1, output_tokens: 1 };
  const rounds = splitRounds(
    [
      prompt("old ticket", "2026-10-18T09:00:00Z"),
      assistant("old", "claude-opus-5-5", usage, "2026-10-18T09:00:01Z"),
      prompt("this ticket", "2026-10-19T09:00:00Z"),
      assistant("new", "claude-opus-5-5", usage, "2026-10-19T09:00:01Z"),
    ],
    "2026-10-19T00:00:00Z",
  );

  assert.equal(rounds.length, 1);
  assert.equal(rounds[0][0].usage, usage);
});

test("token_report_prices_cache_writes_reads_and_output_per_model", () => {
  const usage = {
    input_tokens: 1_000_000,
    output_tokens: 1_000_000,
    cache_read_input_tokens: 1_000_000,
    cache_creation_input_tokens: 2_000_000,
    cache_creation: { ephemeral_1h_input_tokens: 1_000_000, ephemeral_5m_input_tokens: 1_000_000 },
  };

  // Opus: 4 input + 20 output + 0.2 read + 5 (5 min write) + 8 (1 h write).
  const opus = sumUsage([{ model: "claude-opus-5-5", usage }]);
  assert.equal(opus.tokens, 5_000_000);
  assert.equal(opus.usd.toFixed(2), "37.20");
  // Sonnet: 2 + 10 + 0.2 + 2.5 + 4.
  assert.equal(sumUsage([{ model: "claude-sonnet-5-5", usage }]).usd.toFixed(1), "18.7");
});

test("token_report_formats_token_counts", () => {
  assert.equal(formatTokens(950), "950");
  assert.equal(formatTokens(12_400), "12k");
  assert.equal(formatTokens(999_500), "1.0M");
  assert.equal(formatTokens(3_420_000), "3.4M");
});

test("token_report_reads_options_and_rejects_unknown_ones", () => {
  assert.equal(parseArgs(["--since", "2026-10-19T00:00:00Z"]).since, "2026-10-19T00:00:00Z");
  assert.equal(parseArgs(["--since", "﻿2026-10-19T00:00:00Z\r"]).since, "2026-10-19T00:00:00Z");
  assert.throws(() => parseArgs(["--since", "garbage"]), /not a valid ISO time/);
  assert.throws(() => parseArgs(["--model", "opus"]), /--model/);
  assert.throws(() => parseArgs(["--since"]), /--since/);
});

test("token_report_counts_a_send_message_resume_as_a_new_round", () => {
  const resume = {
    ...prompt("The coordinator sent a message while you were working:\nFix round 2"),
    isMeta: true,
  };

  assert.equal(isPrompt(resume), true);
  assert.equal(isPrompt({ ...prompt("Base directory for this skill: x"), isMeta: true }), false);
});

test("token_report_does_not_count_injected_reminders_as_new_rounds", () => {
  assert.equal(isPrompt(prompt("<system-reminder>context</system-reminder>")), false);
  assert.equal(isPrompt(prompt("<task-notification>\n<task-id>x</task-id>")), false);
  assert.equal(
    isPrompt({ type: "user", message: { content: [{ type: "text", text: "<system-reminder>x" }] } }),
    false,
  );
});

test("token_report_counts_a_message_once_across_rounds_with_its_largest_usage", () => {
  const rounds = splitRounds(
    [
      prompt("dispatch"),
      assistant("m1", "claude-sonnet-5-5", { input_tokens: 10, output_tokens: 1 }),
      prompt("resume"),
      assistant("m1", "claude-sonnet-5-5", { input_tokens: 10, output_tokens: 40 }),
      assistant("m2", "claude-sonnet-5-5", { input_tokens: 5, output_tokens: 5 }),
    ],
    null,
  );

  assert.equal(rounds.length, 2);
  assert.equal(rounds[0][0].usage.output_tokens, 40);
  assert.equal(sumUsage(rounds.flat()).tokens, 10 + 40 + 5 + 5);
});

test("token_report_skips_undated_entries_when_filtering_by_start_time", () => {
  const undated = { type: "assistant", message: { id: "u", model: "x", usage: { input_tokens: 9 } } };

  assert.equal(splitRounds([undated], "2026-10-19T00:00:00Z").length, 0);
  assert.equal(splitRounds([undated], null).length, 1);
});

test("token_report_finds_the_project_folder_from_a_subfolder_or_a_trailing_slash", (t) => {
  const projectsDir = fs.mkdtempSync(path.join(os.tmpdir(), "token-report-dirs-"));
  const repo = path.resolve(projectsDir, "repo");
  const projectDir = path.join(projectsDir, repo.replace(/[^a-zA-Z0-9]/g, "-"));
  t.after(() => fs.rmSync(projectsDir, { recursive: true, force: true }));
  fs.mkdirSync(projectDir);

  assert.equal(findProjectDir(projectsDir, `${repo}${path.sep}`), projectDir);
  assert.equal(findProjectDir(projectsDir, path.join(repo, "backend", "src")), projectDir);
});

test("token_report_picks_the_newest_session_that_mentions_the_ticket", (t) => {
  const projectDir = fs.mkdtempSync(path.join(os.tmpdir(), "token-report-sessions-"));
  t.after(() => fs.rmSync(projectDir, { recursive: true, force: true }));
  writeJsonl(path.join(projectDir, "ticket.jsonl"), [prompt("/ship-ticket EA-7")]);
  writeJsonl(path.join(projectDir, "other.jsonl"), [prompt("unrelated work")]);
  fs.utimesSync(path.join(projectDir, "ticket.jsonl"), new Date("2026-10-19T10:00:00Z"), new Date("2026-10-19T10:00:00Z"));
  fs.utimesSync(path.join(projectDir, "other.jsonl"), new Date("2026-10-19T11:00:00Z"), new Date("2026-10-19T11:00:00Z"));

  assert.equal(findSession(projectDir, "2026-10-19T09:00:00Z", "EA-7"), "ticket");
  assert.equal(findSession(projectDir, "2026-10-19T09:00:00Z", null), "other");
  assert.throws(() => findSession(projectDir, "2026-10-19T12:00:00Z", "EA-7"), /no session/);
});

test("token_report_prints_one_line_per_agent_and_one_line_per_round", (t) => {
  const projectsDir = fs.mkdtempSync(path.join(os.tmpdir(), "token-report-"));
  const projectDir = path.join(projectsDir, "d--repo");
  const subagents = path.join(projectDir, "s1", "subagents");
  const usage = { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 1_000_000 };
  t.after(() => fs.rmSync(projectsDir, { recursive: true, force: true }));

  writeJsonl(path.join(projectDir, "s1.jsonl"), [
    prompt("/ship-ticket EA-1"),
    assistant("lead1", "claude-opus-5-5", usage),
  ]);
  writeJsonl(path.join(subagents, "agent-a.jsonl"), [
    prompt("implement"),
    assistant("d1", "claude-sonnet-5-5", usage),
    prompt("fix qa-report.md"),
    assistant("d2", "claude-sonnet-5-5", usage),
  ]);
  fs.writeFileSync(path.join(subagents, "agent-a.meta.json"), JSON.stringify({ agentType: "developer" }));

  assert.equal(findProjectDir(projectsDir, "D:\\repo"), projectDir);
  assert.equal(
    formatReport(collectReport(projectDir, "s1", null)),
    [
      "Tokens: lead 1.0M $0.20 · planner 0 $0.00 · developer 2.0M $0.40 · qa 0 $0.00 · reviewer 0 $0.00 · total 3.0M $0.60",
      "Rounds: planner — · developer R1 1.0M $0.20, R2 1.0M $0.20 · qa — · reviewer —",
    ].join("\n"),
  );
});
