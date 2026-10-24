import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { signIn } from "./auth";
import { apiRequest, apiStream, apiUpload, clearCsrfToken } from "./client";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status });
}

let fetchMock: ReturnType<typeof vi.fn>;

function callArg(call: number, arg: number): unknown {
  return (fetchMock.mock.calls[call] as unknown[])[arg];
}

beforeEach(() => {
  clearCsrfToken();
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function headersOf(call: number): Record<string, string> {
  return (callArg(call, 1) as { headers: Record<string, string> }).headers;
}

describe("apiRequest", () => {
  it("sends_no_csrf_header_on_get", async () => {
    fetchMock.mockResolvedValueOnce(json(200, { ok: 1 }));

    const result = await apiRequest("GET", "/auth/session");

    expect(result).toEqual({ ok: true, data: { ok: 1 } });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(callArg(0, 0)).toBe("/api/auth/session");
    expect(callArg(0, 1)).toMatchObject({ credentials: "same-origin" });
    expect(headersOf(0)["X-CSRF-Token"]).toBeUndefined();
  });

  it("fetches_the_csrf_token_once_and_sends_it_on_unsafe_methods", async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, { csrf_token: "tok-1" }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    await apiRequest("POST", "/auth/sign-out");
    await apiRequest("POST", "/auth/sign-out");

    expect(callArg(0, 0)).toBe("/api/auth/csrf");
    expect(headersOf(1)["X-CSRF-Token"]).toBe("tok-1");
    expect(headersOf(2)["X-CSRF-Token"]).toBe("tok-1");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("sends_the_body_as_json", async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, { csrf_token: "t" }))
      .mockResolvedValueOnce(new Response(null, { status: 202 }));

    const result = await apiRequest("POST", "/auth/forgot-password", { email: "a@b.c" });

    expect(result.ok).toBe(true);
    const init = callArg(1, 1) as { body: string; headers: Record<string, string> };
    expect(init.body).toBe('{"email":"a@b.c"}');
    expect(init.headers["Content-Type"]).toBe("application/json");
  });

  it("maps_an_error_response_to_status_and_code", async () => {
    fetchMock.mockResolvedValueOnce(json(401, { detail: "unauthenticated" }));

    expect(await apiRequest("GET", "/auth/session")).toEqual({
      ok: false,
      status: 401,
      code: "unauthenticated",
    });
  });

  it("uses_unknown_when_the_error_body_has_no_code", async () => {
    fetchMock.mockResolvedValueOnce(new Response("<html>", { status: 502 }));

    expect(await apiRequest("GET", "/x")).toEqual({ ok: false, status: 502, code: "unknown" });
  });

  it("maps_a_network_error", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("down"));

    expect(await apiRequest("GET", "/x")).toEqual({ ok: false, status: 0, code: "network" });
  });

  it("refetches_the_csrf_token_after_sign_in", async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, { csrf_token: "old" }))
      .mockResolvedValueOnce(json(200, { default_workspace_id: null }))
      .mockResolvedValueOnce(json(200, { csrf_token: "new" }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    await signIn("a@b.c", "pw");
    await apiRequest("POST", "/auth/sign-out");

    expect(headersOf(1)["X-CSRF-Token"]).toBe("old");
    expect(headersOf(3)["X-CSRF-Token"]).toBe("new");
  });

  it("returns_ok_with_no_data_for_an_empty_204_body", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));

    expect(await apiRequest("GET", "/x")).toEqual({ ok: true, data: undefined });
  });

  it("returns_ok_with_no_data_for_an_empty_202_body", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 202 }));

    expect(await apiRequest("GET", "/x")).toEqual({ ok: true, data: undefined });
  });

  it("returns_ok_with_no_data_for_an_empty_or_non_json_200_body", async () => {
    fetchMock
      .mockResolvedValueOnce(new Response("", { status: 200 }))
      .mockResolvedValueOnce(new Response("not json", { status: 200 }));

    expect(await apiRequest("GET", "/x")).toEqual({ ok: true, data: undefined });
    expect(await apiRequest("GET", "/x")).toEqual({ ok: true, data: undefined });
  });

  it("keeps_network_errors_as_status_zero", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("offline"));

    expect(await apiRequest("GET", "/x")).toEqual({ ok: false, status: 0, code: "network" });
  });
});

describe("apiUpload", () => {
  it("posts_the_raw_body_with_the_given_headers_and_the_csrf_token", async () => {
    const body = new Blob(["abc"]);
    fetchMock
      .mockResolvedValueOnce(json(200, { csrf_token: "tok" }))
      .mockResolvedValueOnce(json(201, { id: "d1" }));

    const result = await apiUpload("/up", body, { "X-File-Name": "a.txt" });

    expect(result).toEqual({ ok: true, data: { id: "d1" } });
    expect(callArg(1, 0)).toBe("/api/up");
    const init = callArg(1, 1) as { method: string; body: Blob };
    expect(init.method).toBe("POST");
    expect(init.body).toBe(body);
    expect(headersOf(1)).toEqual({ "X-File-Name": "a.txt", "X-CSRF-Token": "tok" });
  });

  it("shares_one_csrf_token_request_between_concurrent_uploads", async () => {
    let tokens = 0;
    fetchMock.mockImplementation((url: string) => {
      if (url === "/api/auth/csrf") {
        tokens += 1;
        return Promise.resolve(json(200, { csrf_token: `tok-${tokens}` }));
      }
      return Promise.resolve(json(201, { id: url }));
    });

    const results = await Promise.all(
      [1, 2, 3, 4, 5].map((n) => apiUpload(`/up/${n}`, new Blob(["x"]), {})),
    );

    expect(results.every((result) => result.ok)).toBe(true);
    const urls = fetchMock.mock.calls.map((call) => (call as unknown[])[0]);
    expect(urls.filter((url) => url === "/api/auth/csrf")).toHaveLength(1);
    const posts = fetchMock.mock.calls
      .map((_, index) => index)
      .filter((index) => callArg(index, 0) !== "/api/auth/csrf");
    expect(posts).toHaveLength(5);
    expect(posts.map((index) => headersOf(index)["X-CSRF-Token"])).toEqual(Array(5).fill("tok-1"));
  });

  it("does_not_cache_a_token_that_arrives_after_clear", async () => {
    let release: (response: Response) => void = () => undefined;
    fetchMock
      .mockReturnValueOnce(new Promise<Response>((resolve) => (release = resolve)))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(json(200, { csrf_token: "fresh" }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    const first = apiRequest("POST", "/a");
    clearCsrfToken();
    release(json(200, { csrf_token: "stale" }));
    await first;
    await apiRequest("POST", "/b");

    expect(callArg(2, 0)).toBe("/api/auth/csrf");
    expect(headersOf(3)["X-CSRF-Token"]).toBe("fresh");
  });

  it("maps_an_error_response_to_status_and_code", async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, { csrf_token: "t" }))
      .mockResolvedValueOnce(json(415, { detail: "unsupported_format" }));

    expect(await apiUpload("/up", new Blob(["x"]), {})).toEqual({
      ok: false,
      status: 415,
      code: "unsupported_format",
    });
  });
});

function streamOf(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }),
    { status },
  );
}

describe("apiStream", () => {
  it("sends_the_csrf_header_and_streams_chunks", async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, { csrf_token: "tok" }))
      .mockResolvedValueOnce(streamOf(["ab", "cà"]));
    const chunks: string[] = [];

    const result = await apiStream("/s", { q: 1 }, (text) => chunks.push(text));

    expect(result).toEqual({ ok: true, data: undefined });
    expect(callArg(1, 0)).toBe("/api/s");
    const init = callArg(1, 1) as { method: string; body: string };
    expect(init.method).toBe("POST");
    expect(init.body).toBe('{"q":1}');
    expect(headersOf(1)).toEqual({ "Content-Type": "application/json", "X-CSRF-Token": "tok" });
    expect(chunks.join("")).toBe("abcà");
  });

  it.each([
    [401, { detail: "unauthenticated" }, "unauthenticated"],
    [404, { detail: "not_found" }, "not_found"],
    [503, { detail: "model_unavailable" }, "model_unavailable"],
  ])("maps_%i_like_apiRequest", async (status, body, code) => {
    fetchMock
      .mockResolvedValueOnce(json(200, { csrf_token: "t" }))
      .mockResolvedValueOnce(json(status, body));
    const onChunk = vi.fn();

    expect(await apiStream("/s", {}, onChunk)).toEqual({ ok: false, status, code });
    expect(onChunk).not.toHaveBeenCalled();
  });

  it("maps_a_body_less_502_to_unknown", async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, { csrf_token: "t" }))
      .mockResolvedValueOnce(new Response(null, { status: 502 }));

    expect(await apiStream("/s", {}, vi.fn())).toEqual({ ok: false, status: 502, code: "unknown" });
  });

  it("reports_aborted", async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, { csrf_token: "t" }))
      .mockRejectedValueOnce(new DOMException("aborted", "AbortError"));
    const controller = new AbortController();
    controller.abort();

    expect(await apiStream("/s", {}, vi.fn(), controller.signal)).toEqual({
      ok: false,
      status: 0,
      code: "aborted",
    });
  });

  it("maps_a_network_error", async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, { csrf_token: "t" }))
      .mockRejectedValueOnce(new TypeError("down"));

    expect(await apiStream("/s", {}, vi.fn())).toEqual({ ok: false, status: 0, code: "network" });
  });
});
