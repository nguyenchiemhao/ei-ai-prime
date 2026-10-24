import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { askCollection, type AskEvent } from "./ask";
import { clearCsrfToken } from "./client";

function sse(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(stream, { status });
}

function frame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${typeof data === "string" ? data : JSON.stringify(data)}\n\n`;
}

function csrf(): Response {
  return new Response(JSON.stringify({ csrf_token: "t" }), { status: 200 });
}

const request = { question: "q?", principal: { kind: "anonymous" as const, groups: [] } };

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  clearCsrfToken();
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("askCollection", () => {
  it("parses_passages_delta_done_error", async () => {
    const passage = { number: 1, title: "T", section: null, page: 2, score: 0.5 };
    fetchMock
      .mockResolvedValueOnce(csrf())
      .mockResolvedValueOnce(
        sse([
          frame("passages", { language: "vi", passages: [passage] }),
          frame("delta", { text: "Xin " }),
          frame("mystery", { x: 1 }),
          frame("delta", { text: "chào" }),
          frame("done", { outcome: "answered", answer: "Xin chào [1]", citations: [1] }),
          frame("error", { code: "answer_failed" }),
        ]),
      );
    const events: AskEvent[] = [];

    const result = await askCollection("w 1", "c/1", request, (event) => events.push(event));

    expect(result).toEqual({ ok: true, data: undefined });
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/workspaces/w%201/collections/c%2F1/ask");
    expect(events).toEqual([
      { type: "passages", language: "vi", passages: [passage] },
      { type: "delta", text: "Xin " },
      { type: "delta", text: "chào" },
      { type: "done", outcome: "answered", answer: "Xin chào [1]", citations: [1] },
      { type: "error", code: "answer_failed" },
    ]);
  });

  it("malformed_data_becomes_answer_failed", async () => {
    fetchMock
      .mockResolvedValueOnce(csrf())
      .mockResolvedValueOnce(sse([frame("delta", "{not json")]));
    const events: AskEvent[] = [];

    await askCollection("w", "c", request, (event) => events.push(event));

    expect(events).toEqual([{ type: "error", code: "answer_failed" }]);
  });

  it("returns_the_error_code_before_the_stream", async () => {
    fetchMock
      .mockResolvedValueOnce(csrf())
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "model_unavailable" }), { status: 503 }),
      );
    const onEvent = vi.fn();

    const result = await askCollection("w", "c", request, onEvent);

    expect(result).toEqual({ ok: false, status: 503, code: "model_unavailable" });
    expect(onEvent).not.toHaveBeenCalled();
  });
});
