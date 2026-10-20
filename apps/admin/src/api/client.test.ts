import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { signIn } from "./auth";
import { apiRequest, clearCsrfToken } from "./client";

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
