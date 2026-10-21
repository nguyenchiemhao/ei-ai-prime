import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCsrfToken } from "../api/client";
import { callsTo, mockApi, renderAt, WS } from "../test/renderApp";
import { MULTI_SESSION, signedInApi, WS_B } from "./shellTestKit";

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

const BUILDER_SLUGS = [
  "dashboard",
  "assistants",
  "knowledge",
  "answer-scripts",
  "glossary",
  "skills",
  "channels",
  "members",
];
const BUILDER_SET = [
  "Dashboard",
  "Assistants",
  "Knowledge",
  "Answer Scripts",
  "Glossary",
  "Skills & Connectors",
  "Channels",
  "Members & roles",
];
const ALL_ELEVEN = [
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
];

// [label, workspace role, organization role, the Sidebar items] (docs/architecture/rbac.md).
const ROLE_SETS: [string, string | null, string | null, string[]][] = [
  ["a Builder", "builder", null, BUILDER_SET],
  ["a Workspace Admin", "workspace_admin", null, BUILDER_SET],
  [
    "a Developer",
    "developer",
    null,
    ["Dashboard", "Skills & Connectors", "Channels", "Members & roles"],
  ],
  [
    "a Knowledge Editor",
    "knowledge_editor",
    null,
    ["Dashboard", "Knowledge", "Answer Scripts", "Glossary", "Members & roles"],
  ],
  ["a Reviewer", "reviewer", null, ["Dashboard", "Conversations", "Unanswered", "Members & roles"]],
  ["a Viewer", "viewer", null, ["Dashboard", "Members & roles"]],
  ["an Org Admin", null, "org_admin", [...BUILDER_SET, "Organization"]],
  ["an Org Owner", null, "org_owner", [...BUILDER_SET, "Organization"]],
  ["an Org Admin who is also a Reviewer", "reviewer", "org_admin", ALL_ELEVEN],
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

  it("lists_the_builder_items_in_order_with_workspace_hrefs_and_no_empty_group", async () => {
    await openShell();
    const sidebar = screen.getByTestId("sidebar");
    const groups = within(sidebar).getAllByRole("group");
    expect(groups.map((group) => within(group).getAllByRole("link").length)).toEqual([1, 5, 1, 1]);
    expect(groups.map((group) => group.firstElementChild?.textContent)).toEqual([
      "Overview",
      "Build",
      "Deploy",
      "Settings",
    ]);

    const links = within(sidebar).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual(BUILDER_SET);
    expect(links.map((link) => link.getAttribute("href"))).toEqual(
      BUILDER_SLUGS.map((slug) => `/w/${WS}/${slug}`),
    );
    expect(within(sidebar).queryByText("Chat")).toBeNull();
    expect(within(sidebar).queryByText("Review")).toBeNull();
    expect(within(sidebar).queryByRole("link", { name: "Conversations" })).toBeNull();
    expect(within(sidebar).queryByRole("link", { name: "Organization" })).toBeNull();
  });

  it.each(ROLE_SETS)("shows_only_what_%s_can_use", async (_label, role, orgRole, expected) => {
    const session = {
      ...MULTI_SESSION,
      org_role: orgRole,
      workspaces: [{ id: WS, name: "People Ops", role }],
    };
    mockApi(signedInApi(session));
    renderAt(`/w/${WS}/members`);
    await screen.findByTestId("sidebar");
    const sidebar = screen.getByTestId("sidebar");
    const links = within(sidebar).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual(expected);
    // A heading without items is not in the DOM at all.
    const counts = within(sidebar)
      .getAllByRole("group")
      .map((group) => within(group).getAllByRole("link").length);
    expect(counts.every((count) => count > 0)).toBe(true);
  });

  it("shows_no_item_to_a_member_role_and_no_group_heading", async () => {
    mockApi(
      signedInApi({
        ...MULTI_SESSION,
        workspaces: [{ id: WS, name: "People Ops", role: "member" }],
      }),
    );
    renderAt(`/w/${WS}/dashboard`);
    await screen.findByTestId("sidebar");
    const sidebar = screen.getByTestId("sidebar");
    expect(within(sidebar).queryAllByRole("link")).toEqual([]);
    expect(within(sidebar).queryAllByRole("group")).toEqual([]);
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

  it("shows_the_organization_role_when_there_is_no_workspace_role", async () => {
    mockApi(
      signedInApi({
        ...MULTI_SESSION,
        org_role: "org_owner",
        workspaces: [{ id: WS, name: "People Ops", role: null }],
      }),
    );
    renderAt(`/w/${WS}/dashboard`);
    await screen.findByTestId("sidebar");
    expect(screen.getByTestId("user-menu").textContent).toContain("Org Owner");
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
