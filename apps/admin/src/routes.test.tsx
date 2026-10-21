import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCsrfToken } from "./api/client";
import { createI18n } from "./i18n";
import { routes } from "./routes";

const WS = "11111111-1111-4111-8111-111111111111";

function session(defaultWorkspaceId: string | null) {
  return {
    user: { id: "u1", display_name: "Ann", email: "ann@x.test" },
    organization: { id: "o1", name: "Org" },
    workspaces: defaultWorkspaceId ? [{ id: defaultWorkspaceId, name: "W", role: "member" }] : [],
    default_workspace_id: defaultWorkspaceId,
  };
}

function mockSession(status: number, body: unknown) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })));
}

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <I18nextProvider i18n={createI18n()}>
      <RouterProvider router={router} />
    </I18nextProvider>,
  );
  return router;
}

beforeEach(() => clearCsrfToken());

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("routes", () => {
  it("redirects_a_signed_out_visitor_from_root_to_sign_in", async () => {
    mockSession(401, { detail: "unauthenticated" });
    const router = renderAt("/");
    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
    await screen.findByTestId("sign-in-form");
  });

  it("redirects_a_signed_in_user_from_root_to_the_default_dashboard", async () => {
    mockSession(200, session(WS));
    const router = renderAt("/");
    await waitFor(() => expect(router.state.location.pathname).toBe(`/w/${WS}/dashboard`));
  });

  it("redirects_a_user_without_a_default_workspace_to_no_workspace", async () => {
    mockSession(200, session(null));
    const router = renderAt("/");
    await waitFor(() => expect(router.state.location.pathname).toBe("/no-workspace"));
  });

  it("redirects_a_signed_in_user_away_from_sign_in", async () => {
    mockSession(200, session(WS));
    const router = renderAt("/sign-in");
    await waitFor(() => expect(router.state.location.pathname).toBe(`/w/${WS}/dashboard`));
  });

  it("redirects_a_signed_out_user_from_the_shell_to_sign_in", async () => {
    mockSession(401, { detail: "unauthenticated" });
    const router = renderAt(`/w/${WS}/assistants`);
    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
  });

  it("shows_the_shell_route_to_a_signed_in_user", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        const body = input.startsWith("/api/workspaces/")
          ? {
              id: WS,
              name: "W",
              role: "builder",
              org_role: null,
              permissions: ["assistants.manage", "dashboard.view", "workspace.access"],
            }
          : session(WS);
        return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
      }),
    );
    const router = renderAt(`/w/${WS}/assistants`);
    await screen.findByTestId("area-page");
    expect(router.state.location.pathname).toBe(`/w/${WS}/assistants`);
  });

  it("serves_the_public_password_routes_without_a_session", async () => {
    mockSession(401, { detail: "unauthenticated" });
    const headings = {
      "/forgot-password": "Forgot password",
      "/set-password": "Set your password",
      "/reset": "Reset your password",
    };
    for (const [path, heading] of Object.entries(headings)) {
      cleanup();
      const router = renderAt(path);
      await screen.findByRole("heading", { name: heading });
      expect(router.state.location.pathname).toBe(path);
    }
  });

  it("renders_not_found_for_an_unknown_path", async () => {
    mockSession(401, { detail: "unauthenticated" });
    renderAt("/nope/nothing");
    await screen.findByTestId("not-found");
  });
});
