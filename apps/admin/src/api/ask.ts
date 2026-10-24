import { createSseParser } from "../knowledge/sse";
import { apiStream, type ApiResult } from "./client";

export type AskPrincipal = { kind: "anonymous" | "authenticated"; groups: string[] };
export type AskRequest = { question: string; principal: AskPrincipal };
export type AskPassage = {
  number: number;
  title: string;
  section: string | null;
  page: number | null;
  score: number;
};

export type AskEvent =
  | { type: "passages"; language: "vi" | "en"; passages: AskPassage[] }
  | { type: "delta"; text: string }
  | { type: "done"; outcome: "answered" | "not_found"; answer: string; citations: number[] }
  | { type: "error"; code: "model_unavailable" | "answer_failed" };

const FAILED: AskEvent = { type: "error", code: "answer_failed" };

function toAskEvent(name: string, data: string): AskEvent | null {
  if (name !== "passages" && name !== "delta" && name !== "done" && name !== "error") return null;
  try {
    return { ...(JSON.parse(data) as object), type: name } as AskEvent;
  } catch {
    return FAILED;
  }
}

/** Ask a Collection a question; `onEvent` gets each parsed SSE event as the answer streams in. */
export function askCollection(
  workspaceId: string,
  collectionId: string,
  request: AskRequest,
  onEvent: (event: AskEvent) => void,
  signal?: AbortSignal,
): Promise<ApiResult<void>> {
  const parse = createSseParser(({ event, data }) => {
    const parsed = toAskEvent(event, data);
    if (parsed) onEvent(parsed);
  });
  const path = `/workspaces/${encodeURIComponent(workspaceId)}/collections/${encodeURIComponent(collectionId)}/ask`;
  return apiStream(path, request, parse, signal);
}
