import { render } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";
import { createI18n } from "../i18n";
import { routes } from "../routes";

export const WS = "11111111-1111-4111-8111-111111111111";

export const SESSION = {
  user: { id: "u1", display_name: "Ann", email: "ann@x.test" },
  organization: { id: "o1", name: "Org" },
  workspaces: [{ id: WS, name: "W", role: "member" }],
  default_workspace_id: WS,
};

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status });
}

type Handler = (init: RequestInit | undefined) => Response | Promise<Response>;

function keyOf(input: unknown, init: RequestInit | undefined): string {
  return `${init?.method ?? "GET"} ${String(input).replace(/^\/api/, "")}`;
}

/** Route-based fetch mock: keys are "METHOD /path" (path without the /api prefix). */
export function mockApi(handlers: Record<string, Handler>) {
  const fn = vi.fn((input: unknown, init?: RequestInit) => {
    const key = keyOf(input, init);
    if (key === "GET /auth/csrf") return Promise.resolve(json(200, { csrf_token: "t" }));
    const handler = handlers[key];
    if (!handler) throw new Error(`unexpected request ${key}`);
    return Promise.resolve(handler(init));
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

/** Init objects of the calls made to "METHOD /path". */
export function callsTo(fn: ReturnType<typeof mockApi>, key: string): RequestInit[] {
  return fn.mock.calls
    .filter(([url, init]) => keyOf(url, init) === key)
    .map(([, init]) => init ?? {});
}

export function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <I18nextProvider i18n={createI18n()}>
      <RouterProvider router={router} />
    </I18nextProvider>,
  );
  return router;
}
