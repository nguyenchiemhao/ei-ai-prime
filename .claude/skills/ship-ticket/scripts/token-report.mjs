// Token report of one /ship-ticket run. Reads the Claude Code transcripts of the current session
// (the main session is the Lead, subagents/agent-*.jsonl are the agents) and prints two lines:
// tokens and API-equivalent cost per agent, then per round (one dispatch or one resume = one round).
//   node .claude/skills/ship-ticket/scripts/token-report.mjs --since <ISO time> [--ticket EA-<n>]
//        [--session <id>] [--projects-dir <dir>] [--cwd <dir>]
// Tokens = input + cache writes + cache reads + output, i.e. what the API processed and billed.
// The session used is printed on stderr.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

// USD per million tokens (claude-api skill, cached 2026-10-06). Cache reads are the published
// prices, not a fixed multiple of input. Cache writes: 5 min = 1.25x input, 1 h = 2x input.
// Haiku cache read is assumed at 0.1x input. Unknown models use the Opus prices.
const PRICES = {
  opus: { input: 4, output: 20, write5m: 5, write1h: 8, read: 0.2 },
  sonnet: { input: 2, output: 10, write5m: 2.5, write1h: 4, read: 0.2 },
  haiku: { input: 0.1, output: 0.5, write5m: 0.125, write1h: 0.2, read: 0.01 },
  fable: { input: 10, output: 50, write5m: 12.5, write1h: 20, read: 0.25 },
};
const AGENT_LABELS = {
  "ticket-planner": "planner",
  developer: "developer",
  "qa-e2e": "qa",
  "code-reviewer": "reviewer",
  designer: "designer",
  "deliver-qa": "qa",
};
// General-purpose agents of /deliver-ticket are labelled by the start of their dispatch description.
const DESCRIPTION_LABELS = [
  [/^builder check/i, "builder"],
  [/^(implement|fix)/i, "implementer"],
  [/^(final review|review)/i, "reviewer"],
];
const REPORTED_AGENTS = ["planner", "developer", "qa", "reviewer"];
const INJECTED_PROMPT = /^\s*<(system-reminder|task-notification)[\s>]/;
// A resume through SendMessage is written as a meta line with this prefix.
const RESUME_PROMPT = /^\s*The coordinator sent a message/;
const USAGE_FIELDS = ["input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"];

// Reads the command-line options; --since must be a valid ISO time (a BOM or CR from a file is removed)
// Input: argv (string[], without node and script)
// Output: { since, ticket, session, projectsDir, cwd }
export const parseArgs = (argv) => {
  const options = {
    since: null,
    ticket: null,
    session: null,
    projectsDir: path.join(os.homedir(), ".claude", "projects"),
    cwd: process.cwd(),
  };
  const keys = {
    "--since": "since",
    "--ticket": "ticket",
    "--session": "session",
    "--projects-dir": "projectsDir",
    "--cwd": "cwd",
  };

  for (let index = 0; index < argv.length; index += 2) {
    const key = keys[argv[index]];
    if (!key || argv[index + 1] === undefined) throw new Error(`unknown or incomplete option: ${argv[index]}`);
    options[key] = argv[index + 1].replace(/^﻿/, "").trim();
  }
  if (options.since !== null && Number.isNaN(Date.parse(options.since))) {
    throw new Error(`--since is not a valid ISO time: "${options.since}"`);
  }
  return options;
};

// Finds the Claude Code project folder of a working directory or of its nearest parent that has one
// (folder names replace every non-alphanumeric character with "-"; the drive letter case may differ)
// Input: projectsDir (string), cwd (string)
// Output: string (absolute folder path)
export const findProjectDir = (projectsDir, cwd) => {
  const names = fs.readdirSync(projectsDir);
  let current = path.resolve(cwd);

  while (true) {
    const wanted = current.replace(/[^a-zA-Z0-9]/g, "-").toLowerCase();
    const match = names.find((name) => name.toLowerCase() === wanted);
    if (match) return path.join(projectsDir, match);
    const parent = path.dirname(current);
    if (parent === current) throw new Error(`no Claude Code project folder for ${cwd} in ${projectsDir}`);
    current = parent;
  }
};

// Picks the session of the run: the most recently written transcript that changed after `since`
// and, when a ticket is given, mentions it
// Input: projectDir (string), since (string | null), ticket (string | null)
// Output: string (session id)
export const findSession = (projectDir, since, ticket) => {
  const sinceTime = since ? Date.parse(since) : -Infinity;
  const sessions = fs
    .readdirSync(projectDir)
    .filter((name) => name.endsWith(".jsonl"))
    .map((name) => ({ name, mtime: fs.statSync(path.join(projectDir, name)).mtimeMs }))
    .filter((session) => session.mtime >= sinceTime)
    .sort((a, b) => b.mtime - a.mtime);
  const match = sessions.find(
    (session) => !ticket || fs.readFileSync(path.join(projectDir, session.name), "utf8").includes(ticket),
  );

  if (!match) throw new Error(`no session transcript in ${projectDir} for ${ticket ?? "this run"}`);
  return match.name.replace(/\.jsonl$/, "");
};

// Reads a JSON Lines transcript; unreadable lines are skipped
// Input: file (string)
// Output: object[]
export const readJsonl = (file) => {
  const entries = [];

  for (const line of fs.readFileSync(file, "utf8").split("\n")) {
    if (!line.trim()) continue;
    try {
      entries.push(JSON.parse(line));
    } catch {
      // A line cut by a crash or an in-progress write carries no usable usage.
    }
  }
  return entries;
};

// Tells whether a transcript entry is a new prompt (a dispatch or a resume), not a tool result
// or an injected reminder / task notification
// Input: entry (object)
// Output: boolean
export const isPrompt = (entry) => {
  const content = entry.message?.content;

  if (entry.type !== "user") return false;
  if (typeof content === "string" && RESUME_PROMPT.test(content)) return true;
  if (entry.isMeta) return false;
  if (typeof content === "string") return !INJECTED_PROMPT.test(content);
  if (!Array.isArray(content) || content.some((block) => block.type === "tool_result")) return false;
  const text = content.find((block) => block.type === "text")?.text ?? "";
  return !INJECTED_PROMPT.test(text);
};

// Merges two usage blocks of the same API message, keeping the largest value of every field
// (streamed lines repeat the usage, sometimes with partial counts)
// Input: a (object), b (object)
// Output: object
const mergeUsage = (a, b) => {
  const merged = { ...a, ...b };

  for (const field of USAGE_FIELDS) merged[field] = Math.max(a[field] ?? 0, b[field] ?? 0);
  merged.cache_creation = {
    ephemeral_1h_input_tokens: Math.max(
      a.cache_creation?.ephemeral_1h_input_tokens ?? 0,
      b.cache_creation?.ephemeral_1h_input_tokens ?? 0,
    ),
  };
  return merged;
};

// Splits a transcript into rounds at every prompt, counting each API message id once, in the round
// where it first appears
// Input: entries (object[]), since (string | null, ISO time; older or undated entries are ignored)
// Output: Array<Array<{ model: string, usage: object }>>
export const splitRounds = (entries, since) => {
  const sinceTime = since ? Date.parse(since) : null;
  const rounds = [];
  const messages = new Map();

  for (const entry of entries) {
    const time = Date.parse(entry.timestamp);
    if (sinceTime !== null && (Number.isNaN(time) || time < sinceTime)) continue;
    if (isPrompt(entry) || rounds.length === 0) rounds.push(new Map());
    if (!entry.message?.usage || !entry.message.id) continue;
    const known = messages.get(entry.message.id);
    if (known) {
      known.usage = mergeUsage(known.usage, entry.message.usage);
    } else {
      const message = { model: entry.message.model ?? "", usage: entry.message.usage };
      messages.set(entry.message.id, message);
      rounds[rounds.length - 1].set(entry.message.id, message);
    }
  }
  return rounds.map((round) => [...round.values()]).filter((round) => round.length > 0);
};

// Returns the price table of a model id
// Input: model (string)
// Output: { input, output, write5m, write1h, read }
export const priceFor = (model) => {
  const family = Object.keys(PRICES).find((name) => model.includes(name));
  return PRICES[family ?? "opus"];
};

// Returns the report label of a subagent from its meta file: its agent type, or for a
// general-purpose agent the role its dispatch description starts with
// Input: meta ({ agentType?: string, description?: string })
// Output: string
export const labelFor = (meta) => {
  const byType = AGENT_LABELS[meta.agentType];
  const byDescription = DESCRIPTION_LABELS.find(([pattern]) => pattern.test(meta.description ?? ""));

  return byType ?? byDescription?.[1] ?? "other";
};

// Computes processed tokens and API-equivalent cost of a list of API messages
// Input: messages (Array<{ model, usage }>)
// Output: { tokens: number, usd: number }
export const sumUsage = (messages) => {
  let tokens = 0;
  let usd = 0;

  for (const { model, usage } of messages) {
    const price = priceFor(model);
    const write = usage.cache_creation_input_tokens ?? 0;
    const write1h = usage.cache_creation?.ephemeral_1h_input_tokens ?? 0;
    const write5m = write - write1h;
    const input = usage.input_tokens ?? 0;
    const read = usage.cache_read_input_tokens ?? 0;
    const output = usage.output_tokens ?? 0;

    tokens += input + write + read + output;
    usd +=
      (input * price.input +
        output * price.output +
        write5m * price.write5m +
        write1h * price.write1h +
        read * price.read) /
      1e6;
  }
  return { tokens, usd };
};

// Collects the Lead total and the per-round totals of every agent of a session
// Input: projectDir (string), session (string), since (string | null)
// Output: { lead: { tokens, usd }, agents: Map<string, Array<{ tokens, usd }>> }
export const collectReport = (projectDir, session, since) => {
  const leadRounds = splitRounds(readJsonl(path.join(projectDir, `${session}.jsonl`)), since);
  const subagentDir = path.join(projectDir, session, "subagents");
  const agents = new Map(REPORTED_AGENTS.map((label) => [label, []]));
  const files = fs.existsSync(subagentDir)
    ? fs.readdirSync(subagentDir).filter((name) => /^agent-.+\.jsonl$/.test(name))
    : [];

  for (const name of files.sort()) {
    const metaFile = path.join(subagentDir, name.replace(/\.jsonl$/, ".meta.json"));
    const meta = fs.existsSync(metaFile) ? JSON.parse(fs.readFileSync(metaFile, "utf8")) : {};
    const label = labelFor(meta);
    const rounds = splitRounds(readJsonl(path.join(subagentDir, name)), since).map(sumUsage);

    if (rounds.length === 0) continue;
    agents.set(label, [...(agents.get(label) ?? []), ...rounds]);
  }
  return { lead: sumUsage(leadRounds.flat()), agents };
};

// Formats a token count as 950, 12k or 3.4M
// Input: tokens (number)
// Output: string
export const formatTokens = (tokens) => {
  if (tokens < 1000) return String(tokens);
  if (Math.round(tokens / 1000) < 1000) return `${Math.round(tokens / 1000)}k`;
  return `${(tokens / 1e6).toFixed(1)}M`;
};

// Formats one total as "<tokens> $<usd>"
// Input: total ({ tokens, usd })
// Output: string
const formatTotal = ({ tokens, usd }) => `${formatTokens(tokens)} $${usd.toFixed(2)}`;

// Builds the two report lines: per agent, then per round
// Input: report ({ lead, agents })
// Output: string (two lines)
export const formatReport = ({ lead, agents }) => {
  const agentTotals = [...agents].map(([label, rounds]) => [label, sumTotals(rounds)]);
  const total = sumTotals([lead, ...agentTotals.map(([, value]) => value)]);
  const perAgent = agentTotals.map(([label, value]) => `${label} ${formatTotal(value)}`);
  const perRound = [...agents].map(([label, rounds]) =>
    rounds.length === 0
      ? `${label} —`
      : `${label} ${rounds.map((round, index) => `R${index + 1} ${formatTotal(round)}`).join(", ")}`,
  );

  return [
    `Tokens: lead ${formatTotal(lead)} · ${perAgent.join(" · ")} · total ${formatTotal(total)}`,
    `Rounds: ${perRound.join(" · ")}`,
  ].join("\n");
};

// Adds up several totals
// Input: totals (Array<{ tokens, usd }>)
// Output: { tokens, usd }
const sumTotals = (totals) =>
  totals.reduce((sum, value) => ({ tokens: sum.tokens + value.tokens, usd: sum.usd + value.usd }), {
    tokens: 0,
    usd: 0,
  });

// Entry point: prints the report of the current (or given) session
// Input: argv (string[])
// Output: void
const main = (argv) => {
  const options = parseArgs(argv);
  const projectDir = findProjectDir(options.projectsDir, options.cwd);
  const session = options.session ?? findSession(projectDir, options.since, options.ticket);

  console.error(`token-report: session ${session}`);
  console.log(formatReport(collectReport(projectDir, session, options.since)));
};

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  try {
    main(process.argv.slice(2));
  } catch (error) {
    console.error(`token-report: ${error.message}`);
    process.exit(1);
  }
}
