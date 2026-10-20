import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCsrfToken } from "../api/client";
import { callsTo, mockApi, renderAt, WS } from "../test/renderApp";
import { signedInApi, WS_B } from "./shellTestKit";

beforeEach(() => clearCsrfToken());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function openShell(path = `/w/${WS}/assistants`, extra: Parameters<typeof mockApi>[0] = {}) {
  const api = mockApi({ ...signedInApi(), ...extra });
  const router = renderAt(path);
  await screen.findByTestId("sidebar");
  return { api, router };
}

const SLUGS = [
  "dashboard",
  "assistants",
  "knowledge",
  "answer-scripts",
  "glossary",
  "skills",
  "channels",
  "conversations",
  "unanswered",
  "members",
  "organization",
];

describe("Sidebar", () => {
  it("shows_the_logo_prototype_tag_and_main_landmark", async () => {
    await openShell();
    const sidebar = screen.getByTestId("sidebar");
    expect(sidebar.tagName).toBe("NAV");
    expect(sidebar.getAttribute("aria-label")).toBe("Main");
    expect(within(sidebar).getByText("ei-ai")).not.toBeNull();
    expect(within(sidebar).getByText("Prototype")).not.toBeNull();
  });

  it("lists_five_groups_and_eleven_items_in_order_with_workspace_hrefs", async () => {
    await openShell();
    const sidebar = screen.getByTestId("sidebar");
    const groups = within(sidebar).getAllByRole("group");
    expect(groups.map((group) => within(group).getAllByRole("link").length)).toEqual([
      1, 5, 1, 2, 2,
    ]);
    expect(groups.map((group) => group.firstElementChild?.textContent)).toEqual([
      "Overview",
      "Build",
      "Deploy",
      "Review",
      "Settings",
    ]);

    const links = within(sidebar).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Dashboard",
      "Assistants",
      "Knowledge",
      "Answer Scripts",
      "Glossary",
      "Skills & Connectors",
      "Channels",
      "Conversations",
      "Unanswered",
      "Members & roles",
      "Organization",
    ]);
    expect(links.map((link) => link.getAttribute("href"))).toEqual(
      SLUGS.map((slug) => `/w/${WS}/${slug}`),
    );
    expect(within(sidebar).queryByText("Chat")).toBeNull();
  });

  it("marks_only_the_active_item_with_aria_current_page", async () => {
    await openShell(`/w/${WS}/glossary`);
    const current = screen
      .getAllByRole("link")
      .filter((link) => link.getAttribute("aria-current") === "page");
    expect(current.map((link) => link.textContent)).toEqual(["Glossary"]);
  });

  it("shows_the_organization_name_and_a_one_item_menu_marked_current", async () => {
    await openShell();
    const button = screen.getByTestId("org-switcher");
    expect(button.textContent).toContain("Organization");
    expect(button.textContent).toContain("Mekong Devworks");
    fireEvent.click(button);
    const items = within(screen.getByRole("menu")).getAllByRole("menuitemradio");
    expect(items.map((item) => item.textContent)).toEqual(["Mekong Devworks"]);
    expect(items[0]?.getAttribute("aria-checked")).toBe("true");
  });

  it("lists_own_workspaces_sorted_with_the_current_one_checked", async () => {
    await openShell();
    const button = screen.getByTestId("workspace-switcher");
    expect(button.textContent).toContain("Workspace");
    expect(button.textContent).toContain("People Ops");
    fireEvent.click(button);
    const items = within(screen.getByRole("menu")).getAllByRole("menuitemradio");
    expect(items.map((item) => item.textContent)).toEqual(["Finance", "People Ops"]);
    expect(items.map((item) => item.getAttribute("aria-checked"))).toEqual(["false", "true"]);
  });

  it("switches_workspace_keeping_the_area_and_never_shows_the_old_one", async () => {
    const { router } = await openShell(`/w/${WS}/glossary`);
    fireEvent.click(screen.getByTestId("workspace-switcher"));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Finance" }));
    expect(router.state.location.pathname).toBe(`/w/${WS_B}/glossary`);
    await waitFor(() =>
      expect(screen.getByTestId("workspace-switcher").textContent).toContain("Finance"),
    );
    expect(screen.queryByText("People Ops")).toBeNull();
    const hrefs = screen.getAllByRole("link").map((link) => link.getAttribute("href"));
    expect(hrefs.every((href) => href?.startsWith(`/w/${WS_B}/`))).toBe(true);
  });

  it("shows_initials_name_and_workspace_role_on_the_user_menu", async () => {
    await openShell();
    const button = screen.getByTestId("user-menu");
    expect(button.textContent).toContain("MP");
    expect(button.textContent).toContain("Minh Pham");
    expect(button.textContent).toContain("Builder");
  });

  it("uses_the_role_in_the_current_workspace", async () => {
    await openShell(`/w/${WS_B}/dashboard`);
    expect(screen.getByTestId("user-menu").textContent).toContain("Viewer");
  });

  it("signs_out_from_the_user_menu_and_goes_to_sign_in", async () => {
    const { api, router } = await openShell(`/w/${WS}/assistants`, {
      "POST /auth/sign-out": () => new Response(null, { status: 204 }),
    });
    fireEvent.click(screen.getByTestId("user-menu"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
    expect(callsTo(api, "POST /auth/sign-out")).toHaveLength(1);
  });

  it("closes_a_menu_with_escape", async () => {
    await openShell();
    fireEvent.click(screen.getByTestId("user-menu"));
    expect(screen.getByRole("menu")).not.toBeNull();
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
  });
});
