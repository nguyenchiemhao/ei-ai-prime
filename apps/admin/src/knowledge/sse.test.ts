import { describe, expect, it } from "vitest";
import { createSseParser, type SseEvent } from "./sse";

function collect(): { events: SseEvent[]; feed: (chunk: string) => void } {
  const events: SseEvent[] = [];
  return { events, feed: createSseParser((event) => events.push(event)) };
}

describe("createSseParser", () => {
  it("parses_one_frame", () => {
    const { events, feed } = collect();
    feed('event: delta\ndata: {"text":"a"}\n\n');
    expect(events).toEqual([{ event: "delta", data: '{"text":"a"}' }]);
  });

  it("parses_two_frames_in_one_chunk", () => {
    const { events, feed } = collect();
    feed("event: a\ndata: 1\n\nevent: b\ndata: 2\n\n");
    expect(events).toEqual([
      { event: "a", data: "1" },
      { event: "b", data: "2" },
    ]);
  });

  it("parses_one_frame_over_three_chunks", () => {
    const { events, feed } = collect();
    feed("event: do");
    feed("ne\ndata: {}");
    expect(events).toEqual([]);
    feed("\n\n");
    expect(events).toEqual([{ event: "done", data: "{}" }]);
  });

  it("handles_crlf_line_endings", () => {
    const { events, feed } = collect();
    feed("event: a\r\ndata: 1\r\n\r\nevent: b\r\ndata: 2\r\n\r\n");
    expect(events).toEqual([
      { event: "a", data: "1" },
      { event: "b", data: "2" },
    ]);
  });

  it("handles_a_crlf_pair_split_across_chunks", () => {
    const { events, feed } = collect();
    feed("event: a\r\ndata: 1\r");
    feed("\n\r");
    feed("\n");
    expect(events).toEqual([{ event: "a", data: "1" }]);
  });

  it("ignores_comment_lines", () => {
    const { events, feed } = collect();
    feed(": ping\n\n");
    feed(": ping\nevent: a\ndata: 1\n\n");
    expect(events).toEqual([{ event: "a", data: "1" }]);
  });

  it("joins_multi_line_data_with_newlines", () => {
    const { events, feed } = collect();
    feed("event: a\ndata: x\ndata: y\n\n");
    expect(events).toEqual([{ event: "a", data: "x\ny" }]);
  });
});
