import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCsrfToken } from "../api/client";
import { callsTo, json, mockApi, renderAt, SESSION } from "../test/renderApp";

beforeEach(() => clearCsrfToken());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("NoWorkspacePage", () => {
  it("shows_the_copy_and_signs_out", async () => {
    const api = mockApi({
      "GET /auth/session": () =>
        json(200, { ...SESSION, workspaces: [], default_workspace_id: null }),
      "POST /auth/sign-out": () => new Response(null, { status: 204 }),
    });
    const router = renderAt("/no-workspace");
    await screen.findByTestId("no-workspace");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("No Workspace yet");
    expect(
      screen.getByText("You are not a member of any Workspace yet. Ask your organization admin."),
    ).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
    expect(callsTo(api, "POST /auth/sign-out")).toHaveLength(1);
  });
});
