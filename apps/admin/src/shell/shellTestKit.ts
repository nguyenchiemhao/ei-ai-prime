import { json, SESSION, WS } from "../test/renderApp";

export const WS_B = "22222222-2222-4222-8222-222222222222";

export const MULTI_SESSION = {
  ...SESSION,
  user: { id: "u1", display_name: "Minh Pham", email: "minh@x.test" },
  organization: { id: "o1", name: "Mekong Devworks" },
  workspaces: [
    { id: WS_B, name: "Finance", role: "viewer" },
    { id: WS, name: "People Ops", role: "builder" },
  ],
  default_workspace_id: WS,
};

/** Handlers for a signed-in user whose Workspace API answers for the memberships of `session`. */
export function signedInApi(session: typeof MULTI_SESSION = MULTI_SESSION) {
  const handlers: Record<string, () => Response> = {
    "GET /auth/session": () => json(200, session),
  };
  for (const workspace of session.workspaces) {
    handlers[`GET /workspaces/${workspace.id}`] = () => json(200, workspace);
  }
  return handlers;
}
