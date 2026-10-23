import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCsrfToken } from "../api/client";
import type { DocumentItem } from "../api/documents";
import { json, mockApi } from "../test/renderApp";
import { POLL_INTERVAL_MS, useDocuments } from "./useDocuments";

const LIST = "GET /workspaces/w1/collections/c1/documents?folder_id=f1";

const doc = (status: DocumentItem["status"]): DocumentItem => ({
  id: "d1",
  folder_id: "f1",
  name: "a.txt",
  format: "txt",
  size_bytes: 10,
  status,
  progress: null,
  reason: null,
  page_count: null,
  uploaded_by: null,
  created_at: "2026-10-22T00:00:00Z",
  updated_at: "2026-10-22T00:00:00Z",
});

beforeEach(() => clearCsrfToken());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useDocuments", () => {
  it("polls_every_two_seconds_until_no_document_is_active", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const answers = [doc("queued"), doc("processing"), doc("ready")];
    const api = mockApi({
      [LIST]: () => json(200, { documents: [answers.shift()] }),
    });
    const { result } = renderHook(() => useDocuments("w1", "c1", "f1"));

    await waitFor(() => expect(result.current.documents[0]?.status).toBe("queued"));
    expect(POLL_INTERVAL_MS).toBe(2000);
    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS));
    await waitFor(() => expect(result.current.documents[0]?.status).toBe("processing"));
    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS));
    await waitFor(() => expect(result.current.documents[0]?.status).toBe("ready"));
    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3));

    expect(api.mock.calls.filter(([url]) => String(url).includes("/documents"))).toHaveLength(3);
  });

  it("reports_an_error_and_lists_the_whole_collection_without_a_folder", async () => {
    mockApi({
      "GET /workspaces/w1/collections/c1/documents": () => json(404, { detail: "not_found" }),
    });
    const { result } = renderHook(() => useDocuments("w1", "c1", null));

    await waitFor(() => expect(result.current.error).toEqual({ status: 404, code: "not_found" }));
    expect(result.current.documents).toEqual([]);
  });

  it("reload_fetches_the_list_again", async () => {
    const api = mockApi({ [LIST]: () => json(200, { documents: [doc("ready")] }) });
    const { result } = renderHook(() => useDocuments("w1", "c1", "f1"));

    await waitFor(() => expect(result.current.documents).toHaveLength(1));
    act(() => result.current.reload());
    await waitFor(() => expect(api.mock.calls.length).toBe(2));
  });

  it("keeps_polling_after_a_failed_poll_and_keeps_the_last_rows", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const answers = [
      () => json(200, { documents: [doc("processing")] }),
      () => json(500, { detail: "boom" }),
      () => json(200, { documents: [doc("ready")] }),
    ];
    mockApi({ [LIST]: () => (answers.shift() ?? answers[0])?.() as Response });
    const { result } = renderHook(() => useDocuments("w1", "c1", "f1"));

    await waitFor(() => expect(result.current.documents[0]?.status).toBe("processing"));
    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS));
    await waitFor(() => expect(result.current.error?.status).toBe(500));
    expect(result.current.documents[0]?.status).toBe("processing");
    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS));
    await waitFor(() => expect(result.current.documents[0]?.status).toBe("ready"));
    expect(result.current.error).toBeNull();
  });

  it("changing_folder_clears_the_error", async () => {
    mockApi({
      [LIST]: () => json(500, { detail: "boom" }),
      "GET /workspaces/w1/collections/c1/documents?folder_id=f2": () =>
        json(200, { documents: [] }),
    });
    const { result, rerender } = renderHook(({ folder }) => useDocuments("w1", "c1", folder), {
      initialProps: { folder: "f1" },
    });

    await waitFor(() => expect(result.current.error?.status).toBe(500));
    rerender({ folder: "f2" });
    expect(result.current.error).toBeNull();
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeNull();
  });

  it("recovers_after_two_502_polls_once_uploads_finished", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const answers = [
      () => json(200, { documents: [] }),
      () => json(502, { detail: "bad_gateway" }),
      () => json(502, { detail: "bad_gateway" }),
      () => json(200, { documents: [doc("queued")] }),
    ];
    mockApi({
      [LIST]: () => (answers.shift() ?? (() => json(200, { documents: [doc("ready")] })))(),
    });
    const onRecovered = vi.fn();
    const { result } = renderHook(() => useDocuments("w1", "c1", "f1", onRecovered));

    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.reload()); // the uploads of a batch were accepted
    await waitFor(() => expect(result.current.error?.status).toBe(502));
    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS));
    expect(result.current.error?.status).toBe(502);
    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS));
    await waitFor(() => expect(result.current.documents[0]?.status).toBe("queued"));
    expect(result.current.error).toBeNull();
    expect(onRecovered).toHaveBeenCalledTimes(1);
    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS));
    await waitFor(() => expect(result.current.documents[0]?.status).toBe("ready"));
  });

  it("does_not_retry_a_client_error", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const api = mockApi({ [LIST]: () => json(404, { detail: "not_found" }) });
    const { result } = renderHook(() => useDocuments("w1", "c1", "f1"));

    await waitFor(() => expect(result.current.error?.status).toBe(404));
    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3));
    expect(api.mock.calls).toHaveLength(1);
  });
});
