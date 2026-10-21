import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Member } from "../api/members";
import { clearCsrfToken } from "../api/client";
import { MULTI_SESSION, signedInApi } from "../shell/shellTestKit";
import { callsTo, json, mockApi, renderAt, WS } from "../test/renderApp";

beforeEach(() => clearCsrfToken());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** A moment `days` calendar days before today, at noon in the browser zone. */
function daysBefore(days: number): string {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate() - days, 12).toISOString();
}

function member(
  id: string,
  name: string,
  role: string,
  orgRole: string | null,
  lastActive: string | null,
): Member {
  return {
    user_id: id,
    display_name: name,
    email: `${id}@mekong.test`,
    role,
    org_role: orgRole,
    last_active_at: lastActive,
  };
}

// u1 is the signed-in user (MULTI_SESSION), in membership order like the seed.
const MEMBERS: Member[] = [
  member("u1", "Linh Tran", "workspace_admin", "org_admin", daysBefore(0)),
  member("u2", "Minh Pham", "builder", null, daysBefore(0)),
  member("u3", "Thao Nguyen", "knowledge_editor", null, daysBefore(1)),
  member("u4", "Quang Le", "developer", null, daysBefore(3)),
  member("u5", "Hà Vũ", "reviewer", null, null),
  member("u6", "Son Hoang", "viewer", null, daysBefore(0)),
  member("u7", "An Do", "member", null, daysBefore(0)),
];

async function open(
  role: string | null,
  orgRole: string | null,
  extra: Parameters<typeof mockApi>[0] = {},
  members: Member[] = MEMBERS,
) {
  const session = {
    ...MULTI_SESSION,
    org_role: orgRole,
    workspaces: [{ id: WS, name: "People Ops", role }],
  };
  const api = mockApi({
    ...signedInApi(session),
    [`GET /workspaces/${WS}/members`]: () => json(200, { members }),
    ...extra,
  });
  const router = renderAt(`/w/${WS}/members`);
  await screen.findByTestId("members-table");
  return { api, router };
}

const rows = () => screen.getAllByTestId("member-row");
const rowOf = (name: string) =>
  rows().find((row) => within(row).queryByText(name) !== null) as HTMLElement;

describe("MembersPage as a manager", () => {
  it("shows_the_header_subtitle_invite_button_table_and_matrix_without_viewing_as", async () => {
    await open("workspace_admin", null);
    const page = screen.getByTestId("members-page");
    expect(page.tagName).toBe("MAIN");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Members & roles");
    expect(page.textContent).toContain(
      "People Ops workspace. A person can hold a different role in each workspace.",
    );
    expect(page.textContent).not.toContain("Viewing as");
    expect(screen.getByTestId("invite-member").textContent).toBe("Invite member");
    expect(document.title).toBe("Members & roles · ei-ai");
    const table = screen.getByRole("table", { name: "Members" });
    expect(table).toBe(screen.getByTestId("members-table"));
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((header) => header.textContent),
    ).toEqual(["Member", "Role in People Ops", "Last active"]);
    expect(screen.getByRole("heading", { level: 2, name: "What each role can do" })).not.toBeNull();
    expect(screen.getByTestId("role-matrix")).not.toBeNull();
  });

  it("lists_the_members_in_order_with_name_email_org_role_and_last_active", async () => {
    await open("workspace_admin", "org_admin");
    expect(rows().map((row) => row.getAttribute("data-user-id"))).toEqual([
      "u1",
      "u2",
      "u3",
      "u4",
      "u5",
      "u6",
      "u7",
    ]);
    const linh = rowOf("Linh Tran");
    expect(within(linh).getByText("u1@mekong.test")).not.toBeNull();
    expect(within(linh).getByTestId("member-org-role").textContent).toBe("Org Admin");
    expect(within(rowOf("Minh Pham")).queryByTestId("member-org-role")).toBeNull();
    expect(rows().map((row) => within(row).getByTestId("member-last-active").textContent)).toEqual([
      "Today",
      "Today",
      "Yesterday",
      "3 days ago",
      "Never",
      "Today",
      "Today",
    ]);
  });

  it("offers_a_named_role_select_with_the_six_roles_and_text_for_the_member_role", async () => {
    await open("workspace_admin", "org_admin");
    const select = screen.getByRole("combobox", { name: "Role for Minh Pham" });
    expect(
      within(select)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual([
      "Workspace Admin",
      "Developer",
      "Builder",
      "Knowledge Editor",
      "Reviewer",
      "Viewer",
    ]);
    expect((select as HTMLSelectElement).value).toBe("builder");
    // The chat-only Member role is not assignable here: shown as text.
    expect(within(rowOf("An Do")).queryByRole("combobox")).toBeNull();
    expect(within(rowOf("An Do")).getByTestId("member-role").textContent).toBe("Member");
  });

  it("changes_a_role_at_once_and_shows_role_updated", async () => {
    const { api } = await open("workspace_admin", "org_admin", {
      [`PUT /workspaces/${WS}/members/u2`]: () =>
        json(200, member("u2", "Minh Pham", "reviewer", null, daysBefore(0))),
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Role for Minh Pham" }), {
      target: { value: "reviewer" },
    });
    const status = await screen.findByRole("status");
    expect(status.textContent).toBe("Role updated.");
    expect(status.getAttribute("data-testid")).toBe("members-status");
    const [call] = callsTo(api, `PUT /workspaces/${WS}/members/u2`);
    expect(JSON.parse(String(call?.body))).toEqual({ role: "reviewer" });
    expect(
      (screen.getByRole("combobox", { name: "Role for Minh Pham" }) as HTMLSelectElement).value,
    ).toBe("reviewer");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("reverts_and_shows_the_forbidden_alert_when_the_api_refuses", async () => {
    await open("workspace_admin", "org_admin", {
      [`PUT /workspaces/${WS}/members/u2`]: () => json(403, { detail: "forbidden" }),
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Role for Minh Pham" }), {
      target: { value: "viewer" },
    });
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("You don't have permission to do this.");
    expect(alert.getAttribute("data-testid")).toBe("members-error");
    await waitFor(() =>
      expect(
        (screen.getByRole("combobox", { name: "Role for Minh Pham" }) as HTMLSelectElement).value,
      ).toBe("builder"),
    );
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("reverts_and_shows_the_generic_alert_on_any_other_failure", async () => {
    await open("workspace_admin", "org_admin", {
      [`PUT /workspaces/${WS}/members/u2`]: () => json(500, { detail: "internal_error" }),
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Role for Minh Pham" }), {
      target: { value: "viewer" },
    });
    expect((await screen.findByRole("alert")).textContent).toBe("Something went wrong. Try again.");
  });

  it("clears_the_previous_message_when_the_next_change_starts", async () => {
    await open("workspace_admin", "org_admin", {
      [`PUT /workspaces/${WS}/members/u2`]: () =>
        json(200, member("u2", "Minh Pham", "reviewer", null, daysBefore(0))),
      [`PUT /workspaces/${WS}/members/u3`]: () => json(403, { detail: "forbidden" }),
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Role for Minh Pham" }), {
      target: { value: "reviewer" },
    });
    await screen.findByRole("status");
    fireEvent.change(screen.getByRole("combobox", { name: "Role for Thao Nguyen" }), {
      target: { value: "viewer" },
    });
    await screen.findByRole("alert");
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("asks_for_the_workspace_again_after_the_caller_changes_their_own_role", async () => {
    const { api } = await open("workspace_admin", "org_admin", {
      [`PUT /workspaces/${WS}/members/u1`]: () =>
        json(200, member("u1", "Linh Tran", "reviewer", "org_admin", daysBefore(0))),
    });
    expect(callsTo(api, `GET /workspaces/${WS}`)).toHaveLength(1);
    fireEvent.change(screen.getByRole("combobox", { name: "Role for Linh Tran" }), {
      target: { value: "reviewer" },
    });
    await screen.findByRole("status");
    await waitFor(() => expect(callsTo(api, `GET /workspaces/${WS}`)).toHaveLength(2));
  });

  it("does_not_ask_again_after_a_change_of_someone_else", async () => {
    const { api } = await open("workspace_admin", "org_admin", {
      [`PUT /workspaces/${WS}/members/u2`]: () =>
        json(200, member("u2", "Minh Pham", "viewer", null, daysBefore(0))),
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Role for Minh Pham" }), {
      target: { value: "viewer" },
    });
    await screen.findByRole("status");
    expect(callsTo(api, `GET /workspaces/${WS}`)).toHaveLength(1);
  });

  it("makes_the_own_row_editable_only_with_an_organization_role", async () => {
    await open("workspace_admin", null);
    expect(screen.queryByRole("combobox", { name: "Role for Linh Tran" })).toBeNull();
    expect(within(rowOf("Linh Tran")).getByTestId("member-role").textContent).toBe(
      "Workspace Admin",
    );
    expect(screen.getByRole("combobox", { name: "Role for Minh Pham" })).not.toBeNull();
    cleanup();
    vi.unstubAllGlobals();
    clearCsrfToken();

    await open("workspace_admin", "org_admin");
    expect(screen.getByRole("combobox", { name: "Role for Linh Tran" })).not.toBeNull();
  });

  it("lets_an_org_admin_without_a_workspace_role_manage_the_workspace", async () => {
    await open(null, "org_admin", {}, MEMBERS.slice(1));
    expect(screen.getByTestId("invite-member")).not.toBeNull();
    expect(screen.getByRole("combobox", { name: "Role for Minh Pham" })).not.toBeNull();
  });
});

describe("MembersPage pending changes and an ended session", () => {
  it("tracks_each_row_while_two_changes_are_in_flight", async () => {
    const release: Record<string, (response: Response) => void> = {};
    const pending = (id: string) => () =>
      new Promise<Response>((resolve) => {
        release[id] = resolve;
      }) as unknown as Response;
    await open("workspace_admin", "org_admin", {
      [`PUT /workspaces/${WS}/members/u2`]: pending("u2"),
      [`PUT /workspaces/${WS}/members/u3`]: pending("u3"),
    });
    const minh = () => screen.getByRole("combobox", { name: "Role for Minh Pham" });
    const thao = () => screen.getByRole("combobox", { name: "Role for Thao Nguyen" });
    fireEvent.change(minh(), { target: { value: "reviewer" } });
    fireEvent.change(thao(), { target: { value: "viewer" } });
    await waitFor(() => expect((minh() as HTMLSelectElement).disabled).toBe(true));
    expect((thao() as HTMLSelectElement).disabled).toBe(true);

    release["u2"]?.(json(200, member("u2", "Minh Pham", "reviewer", null, daysBefore(0))));
    await waitFor(() => expect((minh() as HTMLSelectElement).disabled).toBe(false));
    // The second change is still pending: its select stays disabled and shows the chosen role.
    expect((thao() as HTMLSelectElement).disabled).toBe(true);
    expect((thao() as HTMLSelectElement).value).toBe("viewer");

    release["u3"]?.(json(200, member("u3", "Thao Nguyen", "viewer", null, daysBefore(1))));
    await waitFor(() => expect((thao() as HTMLSelectElement).disabled).toBe(false));
  });

  it("goes_to_sign_in_when_a_role_change_answers_401", async () => {
    let expired = false;
    const { router } = await open("workspace_admin", "org_admin", {
      "GET /auth/session": () =>
        expired
          ? json(401, { detail: "unauthenticated" })
          : json(200, {
              ...MULTI_SESSION,
              org_role: "org_admin",
              workspaces: [{ id: WS, name: "People Ops", role: "workspace_admin" }],
            }),
      [`PUT /workspaces/${WS}/members/u2`]: () => {
        expired = true;
        return json(401, { detail: "unauthenticated" });
      },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Role for Minh Pham" }), {
      target: { value: "viewer" },
    });
    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
  });
});

describe("MembersPage as a viewer", () => {
  it("shows_the_table_and_matrix_but_no_invite_button_and_no_selects", async () => {
    await open("viewer", null);
    expect(screen.queryByTestId("invite-member")).toBeNull();
    expect(screen.queryByRole("button", { name: "Invite member" })).toBeNull();
    expect(screen.queryAllByRole("combobox")).toEqual([]);
    expect(rows().map((row) => within(row).getByTestId("member-role").textContent)).toEqual([
      "Workspace Admin",
      "Builder",
      "Knowledge Editor",
      "Developer",
      "Reviewer",
      "Viewer",
      "Member",
    ]);
    expect(screen.getAllByTestId("matrix-row")).toHaveLength(8);
  });

  it("shows_an_alert_when_the_list_cannot_be_loaded", async () => {
    mockApi({
      ...signedInApi({
        ...MULTI_SESSION,
        workspaces: [{ id: WS, name: "People Ops", role: "viewer" }],
      }),
      [`GET /workspaces/${WS}/members`]: () => json(500, { detail: "internal_error" }),
    });
    renderAt(`/w/${WS}/members`);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Something went wrong. Try again.");
    expect(screen.queryByTestId("members-table")).toBeNull();
    expect(screen.getByTestId("role-matrix")).not.toBeNull();
  });
});

describe("MembersPage invitation", () => {
  it("opens_the_dialog_invites_adds_the_row_and_returns_focus_to_the_button", async () => {
    const created = member("u8", "New Person", "viewer", null, null);
    const { api } = await open("workspace_admin", "org_admin", {
      [`POST /workspaces/${WS}/members`]: () =>
        json(201, { ...created, email: "new.person@mekong.test" }),
    });
    fireEvent.click(screen.getByTestId("invite-member"));
    const dialog = screen.getByRole("dialog", { name: "Invite member" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Email" }), {
      target: { value: " New.Person@Mekong.test " },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send invite" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("status").textContent).toBe(
      "Invitation created for new.person@mekong.test.",
    );
    expect(rows()).toHaveLength(8);
    expect(within(rows()[7] as HTMLElement).getByTestId("member-last-active").textContent).toBe(
      "Never",
    );
    expect(document.activeElement).toBe(screen.getByTestId("invite-member"));
    const [call] = callsTo(api, `POST /workspaces/${WS}/members`);
    expect(JSON.parse(String(call?.body))).toEqual({
      email: " New.Person@Mekong.test ",
      role: "viewer",
    });
  });
});
