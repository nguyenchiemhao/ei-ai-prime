import { cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCsrfToken } from "../api/client";
import { callsTo, json, mockApi, renderAt, WS } from "../test/renderApp";
import { signedInApi, workspaceInfo, WS_B } from "./shellTestKit";

beforeEach(() => clearCsrfToken());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const UNKNOWN = "33333333-3333-4333-8333-333333333333";

describe("AppShell", () => {
  it("renders_the_area_page_with_heading_empty_text_and_title", async () => {
    mockApi(signedInApi());
    renderAt(`/w/${WS}/answer-scripts`);
    const page = await screen.findByTestId("area-page");
    expect(page.getAttribute("data-area")).toBe("answer-scripts");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Answer Scripts");
    expect(page.textContent).toContain("Nothing here yet.");
    expect(document.title).toBe("Answer Scripts · ei-ai");
  });

  it("renders_not_found_without_the_sidebar_when_the_workspace_api_says_404", async () => {
    mockApi({
      ...signedInApi(),
      [`GET /workspaces/${UNKNOWN}`]: () => json(404, { detail: "not_found" }),
    });
    renderAt(`/w/${UNKNOWN}/dashboard`);
    await screen.findByTestId("not-found");
    expect(screen.queryByTestId("sidebar")).toBeNull();
    expect(screen.queryByTestId("area-page")).toBeNull();
    expect(document.body.textContent).not.toContain(UNKNOWN);
    expect(document.body.textContent).not.toContain("People Ops");
  });

  it("renders_not_found_for_a_malformed_workspace_id_answered_422", async () => {
    mockApi({
      ...signedInApi(),
      "GET /workspaces/not-a-uuid": () => json(422, { detail: "validation_failed" }),
    });
    renderAt("/w/not-a-uuid/dashboard");
    await screen.findByTestId("not-found");
    expect(screen.queryByTestId("sidebar")).toBeNull();
  });

  it("renders_not_found_for_an_unknown_area", async () => {
    mockApi(signedInApi());
    renderAt(`/w/${WS}/chat`);
    await screen.findByTestId("not-found");
    expect(screen.queryByTestId("sidebar")).toBeNull();
  });

  it("shows_no_sidebar_until_the_workspace_check_answers", async () => {
    let release: (response: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    mockApi({
      ...signedInApi(),
      [`GET /workspaces/${WS}`]: () => pending as unknown as Response,
    });
    renderAt(`/w/${WS}/dashboard`);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByTestId("sidebar")).toBeNull();
    release(json(200, workspaceInfo({ id: WS, name: "People Ops" }, "builder")));
    await screen.findByTestId("sidebar");
  });

  it("checks_the_workspace_again_on_every_workspace_and_area_change", async () => {
    const api = mockApi(signedInApi());
    const router = renderAt(`/w/${WS}/dashboard`);
    await screen.findByTestId("sidebar");
    expect(callsTo(api, `GET /workspaces/${WS}`)).toHaveLength(1);
    await router.navigate(`/w/${WS}/glossary`);
    await screen.findByRole("heading", { name: "Glossary" });
    expect(callsTo(api, `GET /workspaces/${WS}`)).toHaveLength(2);
    await router.navigate(`/w/${WS_B}/dashboard`);
    await waitFor(() => expect(callsTo(api, `GET /workspaces/${WS_B}`)).toHaveLength(1));
    await screen.findByTestId("sidebar");
  });

  it("keeps_the_current_page_until_the_check_of_the_next_area_answers", async () => {
    let release: (response: Response) => void = () => undefined;
    let calls = 0;
    mockApi({
      ...signedInApi(),
      [`GET /workspaces/${WS}`]: () => {
        calls += 1;
        if (calls === 1) {
          return json(200, workspaceInfo({ id: WS, name: "People Ops" }, "builder"));
        }
        return new Promise<Response>((resolve) => {
          release = resolve;
        }) as unknown as Response;
      },
    });
    const router = renderAt(`/w/${WS}/dashboard`);
    await screen.findByRole("heading", { name: "Dashboard" });
    await router.navigate(`/w/${WS}/glossary`);
    await waitFor(() => expect(calls).toBe(2));
    expect(screen.getByRole("heading", { name: "Dashboard" })).not.toBeNull();
    expect(screen.queryByRole("heading", { name: "Glossary" })).toBeNull();
    release(json(200, workspaceInfo({ id: WS, name: "People Ops" }, "builder")));
    await screen.findByRole("heading", { name: "Glossary" });
  });

  it("shows_the_no_access_page_inside_the_shell_for_an_area_the_role_does_not_include", async () => {
    mockApi(signedInApi());
    renderAt(`/w/${WS_B}/assistants`); // a Viewer in Finance
    const page = await screen.findByTestId("area-forbidden");
    expect(page.tagName).toBe("MAIN");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("No access");
    expect(page.textContent).toContain(
      "Your role in this workspace does not include this page. Ask a workspace admin if you need it.",
    );
    expect(screen.getByTestId("sidebar")).not.toBeNull();
    expect(screen.queryByTestId("area-page")).toBeNull();
    expect(screen.queryByRole("link", { name: "Assistants" })).toBeNull();
  });

  it("applies_a_role_change_on_the_next_click_without_a_reload", async () => {
    let role = "builder";
    mockApi({
      ...signedInApi(),
      [`GET /workspaces/${WS}`]: () =>
        json(200, workspaceInfo({ id: WS, name: "People Ops" }, role)),
      [`GET /workspaces/${WS}/members`]: () => json(200, { members: [] }),
    });
    const router = renderAt(`/w/${WS}/dashboard`);
    await screen.findByRole("link", { name: "Assistants" });
    role = "viewer"; // an admin changed the role meanwhile
    await router.navigate(`/w/${WS}/members`);
    await screen.findByTestId("members-page");
    expect(screen.queryByRole("link", { name: "Assistants" })).toBeNull();
    expect(screen.getByTestId("user-menu").textContent).toContain("Viewer");
  });

  it("shows_no_access_when_a_hidden_area_url_is_opened_directly", async () => {
    mockApi({
      ...signedInApi(),
      [`GET /workspaces/${WS}`]: () =>
        json(200, workspaceInfo({ id: WS, name: "People Ops" }, "viewer")),
    });
    renderAt(`/w/${WS}/knowledge`);
    await screen.findByTestId("area-forbidden");
  });

  it("renders_the_members_page_for_the_members_area", async () => {
    mockApi({
      ...signedInApi(),
      [`GET /workspaces/${WS}/members`]: () => json(200, { members: [] }),
    });
    renderAt(`/w/${WS}/members`);
    await screen.findByTestId("members-page");
    expect(screen.queryByTestId("area-page")).toBeNull();
  });

  it("renders_the_knowledge_page_for_the_knowledge_area", async () => {
    mockApi({
      ...signedInApi(),
      [`GET /workspaces/${WS}/collections`]: () => json(200, { collections: [] }),
    });
    renderAt(`/w/${WS}/knowledge`);
    await screen.findByTestId("knowledge-page");
    expect(screen.queryByTestId("area-page")).toBeNull();
  });

  it("unknown_area_item_is_not_found", async () => {
    mockApi(signedInApi());
    renderAt(`/w/${WS}/glossary/${UNKNOWN}`);
    await screen.findByTestId("not-found");
    expect(screen.queryByTestId("area-page")).toBeNull();
  });

  it("returns_to_not_found_when_the_role_is_revoked_on_the_next_check", async () => {
    let revoked = false;
    mockApi({
      ...signedInApi(),
      [`GET /workspaces/${WS}`]: () =>
        revoked
          ? json(404, { detail: "not_found" })
          : json(200, workspaceInfo({ id: WS, name: "People Ops" }, "builder")),
    });
    const router = renderAt(`/w/${WS}/dashboard`);
    await screen.findByTestId("sidebar");
    revoked = true;
    await router.navigate(`/w/${WS}/glossary`);
    await screen.findByTestId("not-found");
    expect(screen.queryByTestId("sidebar")).toBeNull();
  });

  it("shows_an_alert_when_the_service_is_unavailable", async () => {
    mockApi({ ...signedInApi(), [`GET /workspaces/${WS}`]: () => json(503, { detail: "x" }) });
    renderAt(`/w/${WS}/dashboard`);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("The service is unavailable. Try again later.");
    expect(screen.queryByTestId("sidebar")).toBeNull();
  });
});
