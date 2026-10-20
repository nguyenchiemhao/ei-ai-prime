import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCsrfToken } from "../api/client";
import { SessionProvider, useSession } from "./SessionProvider";

const SESSION = {
  user: { id: "u1", display_name: "Ann", email: "ann@x.test" },
  organization: { id: "o1", name: "Org" },
  workspaces: [],
  default_workspace_id: null,
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status });
}

function Probe() {
  const { session, loading, refresh, signOut } = useSession();
  return (
    <div>
      <span data-testid="state">
        {loading ? "loading" : session ? session.user.display_name : "anonymous"}
      </span>
      <button onClick={() => void signOut()}>out</button>
      <button onClick={() => void refresh()}>refresh</button>
    </div>
  );
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
  cleanup();
  vi.unstubAllGlobals();
});

describe("SessionProvider", () => {
  it("loads_the_session_on_mount", async () => {
    fetchMock.mockResolvedValueOnce(json(200, SESSION));

    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    );

    expect(screen.getByTestId("state").textContent).toBe("loading");
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("Ann"));
  });

  it("is_anonymous_on_401", async () => {
    fetchMock.mockResolvedValueOnce(json(401, { detail: "unauthenticated" }));

    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("anonymous"));
  });

  it("sign_out_clears_the_session", async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, SESSION))
      .mockResolvedValueOnce(json(200, { csrf_token: "t" }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("Ann"));

    screen.getByText("out").click();

    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("anonymous"));
    expect(callArg(2, 0)).toBe("/api/auth/sign-out");
  });

  it("refresh_populates_the_session_after_an_initial_401", async () => {
    fetchMock
      .mockResolvedValueOnce(json(401, { detail: "unauthenticated" }))
      .mockResolvedValueOnce(json(200, SESSION));
    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("anonymous"));

    screen.getByText("refresh").click();

    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("Ann"));
  });
});
