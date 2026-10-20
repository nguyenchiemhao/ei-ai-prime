import { cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCsrfToken } from "../api/client";
import { callsTo, json, mockApi, renderAt, WS } from "../test/renderApp";
import { signedInApi, WS_B } from "./shellTestKit";

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
    release(json(200, { id: WS, name: "People Ops", role: "builder" }));
    await screen.findByTestId("sidebar");
  });

  it("checks_the_workspace_again_on_workspace_change_but_not_on_area_change", async () => {
    const api = mockApi(signedInApi());
    const router = renderAt(`/w/${WS}/dashboard`);
    await screen.findByTestId("sidebar");
    await router.navigate(`/w/${WS}/glossary`);
    await screen.findByRole("heading", { name: "Glossary" });
    expect(callsTo(api, `GET /workspaces/${WS}`)).toHaveLength(1);
    await router.navigate(`/w/${WS_B}/glossary`);
    await waitFor(() => expect(callsTo(api, `GET /workspaces/${WS_B}`)).toHaveLength(1));
    await screen.findByTestId("sidebar");
  });

  it("shows_an_alert_when_the_service_is_unavailable", async () => {
    mockApi({ ...signedInApi(), [`GET /workspaces/${WS}`]: () => json(503, { detail: "x" }) });
    renderAt(`/w/${WS}/dashboard`);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("The service is unavailable. Try again later.");
    expect(screen.queryByTestId("sidebar")).toBeNull();
  });
});
