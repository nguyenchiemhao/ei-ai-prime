export type SseEvent = { event: string; data: string };

/**
 * Incremental parser for a `text/event-stream` body: feed it decoded text in any chunking and it
 * calls `onEvent` once per complete frame (blank-line terminated). Comment lines (`: ping`) are
 * ignored, several `data:` lines join with `\n`, and `\r\n` is treated like `\n`.
 */
export function createSseParser(onEvent: (event: SseEvent) => void): (chunk: string) => void {
  let buffer = "";

  function emit(frame: string): void {
    let event = "message";
    const data: string[] = [];
    for (const line of frame.split("\n")) {
      if (line === "" || line.startsWith(":")) continue;
      const colon = line.indexOf(":");
      const field = colon === -1 ? line : line.slice(0, colon);
      let value = colon === -1 ? "" : line.slice(colon + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "event") event = value;
      else if (field === "data") data.push(value);
    }
    if (data.length > 0) onEvent({ event, data: data.join("\n") });
  }

  return (chunk) => {
    // A "\r" at the end may be the first half of "\r\n": keep it unconverted until more arrives.
    buffer += chunk;
    const normalized = buffer.replace(/\r\n/g, "\n");
    const held = normalized.endsWith("\r") ? "\r" : "";
    buffer = (held ? normalized.slice(0, -1) : normalized).replace(/\r/g, "\n") + held;
    let end = buffer.indexOf("\n\n");
    while (end !== -1) {
      emit(buffer.slice(0, end));
      buffer = buffer.slice(end + 2);
      end = buffer.indexOf("\n\n");
    }
  };
}
