// EA-37 (KB-06) AC5 Streaming (tier @perf). Black-box, from .work/EA-37/contract.md only. What is proven on the
// dev machine: the answer STREAMS (the answer box shows at least two different non-empty texts while
// data-outcome is still "answering"; the API sends several delta frames before done). The first-token time is
// RECORDED, not gated: "<= 3 s on the reference configuration" is DEFERRED to EVL-02 (EA-17, EA-30).
// Needs the stack with the `model` profile:
//   npm run up && npm run seed && npm run e2e:perf -- e2e/knowledge/EA-37-ask-collection-perf.spec.ts
// Results go to .work/EA-37/perf-ac5.json. Data: one collection `qa-EA37-<run> Handbook`; removed in afterAll.
import { mkdirSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { withSession } from "../support/ea23";
import { embeddingHealthy } from "../support/ea35";
import {
  Q,
  SCREENSHOTS_37,
  answerText,
  ask,
  buildAskFixtures,
  cleanup37,
  clickAsk,
  counts37,
  expectStream,
  expectValidCitations,
  markerRows37,
  observeAnswer,
  openAskPanel,
  readAnswerLog,
  saveResult,
  settle,
  type AskFixtures,
  type Counts37,
} from "../support/ea37";

test.describe.configure({ mode: "serial", timeout: 900_000 });

let baseline: Counts37 | undefined;
let fx: Required<Pick<AskFixtures, "ws" | "thao" | "handbook">>;

test.beforeAll(async () => {
  test.setTimeout(1_200_000);
  await cleanup37();
  baseline = counts37();
  expect(embeddingHealthy(), "precondition: the embedding service is healthy (profile model)").toBe(
    true,
  );
  fx = (await buildAskFixtures(["handbook"])) as typeof fx;
  mkdirSync(SCREENSHOTS_37, { recursive: true });
});

test.afterAll(async () => {
  await cleanup37();
  if (baseline) expect(counts37(), "rows left behind").toEqual(baseline);
  expect(markerRows37(), "rows with the EA-37 marker left behind").toEqual([]);
});

const median = (values: number[]): number => {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)] ?? Number.NaN;
};

test(
  "AC5: the answer streams: the box grows before done; click-to-first-text and click-to-done are recorded (<= 3 s is deferred to EVL-02)",
  { tag: "@perf" },
  async ({ browser }) => {
    const principal = { kind: "authenticated", groups: [] as string[] };

    // Cold ask (the chat model may still be loading): recorded, not measured against anything.
    const cold = await ask(fx.thao, fx.ws, fx.handbook.id, { question: Q.marryEn, principal });
    const coldSummary = expectStream(cold, { label: "cold" });
    expectValidCitations(coldSummary, "cold");

    // Warm asks through the API: frame timing as seen by a client of the admin origin.
    const warm: { passagesMs: number; firstDeltaMs: number; doneMs: number; deltas: number }[] = [];
    for (let i = 0; i < 3; i += 1) {
      const r = await ask(fx.thao, fx.ws, fx.handbook.id, { question: Q.marryEn, principal });
      const s = expectStream(r, { label: `warm ${i + 1}` });
      expectValidCitations(s, `warm ${i + 1}`);
      expect(s.done?.outcome).toBe("answered");
      expect(
        s.deltas.length,
        "the answer arrives in several delta frames, not one block",
      ).toBeGreaterThanOrEqual(2);
      expect(r.firstDeltaMs, "a delta arrives").not.toBeNull();
      const delta = r.firstDeltaMs ?? Number.NaN;
      expect(delta, "the first delta comes after the passages frame").toBeGreaterThanOrEqual(
        r.firstFrameMs ?? 0,
      );
      expect(delta, "and before the stream ends").toBeLessThan(r.totalMs);
      warm.push({
        passagesMs: Math.round(r.firstFrameMs ?? -1),
        firstDeltaMs: Math.round(delta),
        doneMs: Math.round(r.totalMs),
        deltas: s.deltas.length,
      });
    }

    // The same through the UI: what the person sees grows before the outcome leaves "answering".
    let uiResult: { firstTextMs: number; doneMs: number; distinctTexts: number } | null = null;
    await withSession(browser, fx.thao, async (page) => {
      await observeAnswer(page);
      await openAskPanel(page, fx.ws, fx.handbook.id);
      await clickAsk(page, Q.marryEn);
      expect(await settle(page)).toBe("answered");
      const { clickAt, samples } = await readAnswerLog(page);
      expect(clickAt, "the click was observed in the page").toBeGreaterThan(0);
      const answering = samples.filter((s) => s.outcome === "answering");
      const texts = [...new Set(answering.map((s) => s.text).filter((t) => t !== ""))];
      expect(
        texts.length,
        `non-empty texts seen while answering (the answer must grow before done): ${JSON.stringify(texts)}`,
      ).toBeGreaterThanOrEqual(2);
      for (let i = 1; i < texts.length; i += 1) {
        expect((texts[i] as string).length, "the text only grows").toBeGreaterThanOrEqual(
          (texts[i - 1] as string).length,
        );
      }
      const first = answering.find((s) => s.text !== "");
      const finished = samples.find((s) => s.outcome === "answered");
      expect(first && finished, "samples for the first text and for the final answer").toBeTruthy();
      uiResult = {
        firstTextMs: Math.round((first?.t ?? 0) - clickAt),
        doneMs: Math.round((finished?.t ?? 0) - clickAt),
        distinctTexts: texts.length,
      };
      expect(uiResult.firstTextMs, "first text before the final answer").toBeLessThan(
        uiResult.doneMs,
      );
      expect(await answerText(page)).toContain("3");
      await page
        .getByTestId("ask-panel")
        .screenshot({ path: `${SCREENSHOTS_37}/ac5-streamed-answer.png` });
    });

    const result = {
      note: "recorded on the dev machine; the gate (first token <= 3 s on the reference configuration, D57) is deferred to EVL-02",
      coldFirstDeltaMs: Math.round(cold.firstDeltaMs ?? -1),
      coldDoneMs: Math.round(cold.totalMs),
      warm,
      warmMedianFirstDeltaMs: median(warm.map((w) => w.firstDeltaMs)),
      ui: uiResult,
    };
    saveResult("perf-ac5.json", result);
    test.info().annotations.push({ type: "observation", description: JSON.stringify(result) });
  },
);
