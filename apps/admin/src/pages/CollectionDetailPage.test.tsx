import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCsrfToken } from "../api/client";
import type { CollectionDetail, FolderItem } from "../api/collections";
import { MULTI_SESSION, signedInApi } from "../shell/shellTestKit";
import { callsTo, json, mockApi, renderAt, WS } from "../test/renderApp";

beforeEach(() => clearCsrfToken());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const BASE = `/workspaces/${WS}/collections`;
const DETAIL = `GET ${BASE}/c1`;

function folder(id: string, name: string, depth: number, parentId: string | null): FolderItem {
  return { id, name, depth, parent_id: parentId };
}

const FOLDERS: FolderItem[] = [
  folder("f1", "Policies", 1, null),
  folder("f2", "2026", 2, "f1"),
  folder("f3", "Q1", 3, "f2"),
];

function makeDetail(extra: Partial<CollectionDetail> = {}): CollectionDetail {
  return {
    id: "c1",
    name: "Employee Handbook",
    subtitle: null,
    access_level: "authenticated",
    groups: [],
    local_only: true,
    documents: { total: 0, ready: 0, processing: 0, needs_attention: 0 },
    used_by: [],
    created_at: "2026-10-20T00:00:00Z",
    updated_at: "2026-10-20T00:00:00Z",
    folders: FOLDERS,
    ...extra,
  };
}

async function open(
  handlers: Parameters<typeof mockApi>[0] = {},
  detail: CollectionDetail = makeDetail(),
) {
  const session = {
    ...MULTI_SESSION,
    workspaces: [{ id: WS, name: "People Ops", role: "workspace_admin" }],
  };
  const api = mockApi({
    ...signedInApi(session),
    [DETAIL]: () => json(200, detail),
    ...handlers,
  });
  const router = renderAt(`/w/${WS}/knowledge/c1`);
  await screen.findByTestId("collection-detail");
  return { api, router };
}

const folderRow = (name: string) =>
  screen.getAllByTestId("folder-row").find((row) => row.textContent?.includes(name)) as HTMLElement;

describe("CollectionDetailPage", () => {
  it("renders_breadcrumb_badges_and_folder_tree", async () => {
    await open();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Employee Handbook");
    expect(document.title).toBe("Employee Handbook · ei-ai");
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Knowledge" })).toBeTruthy();
    expect(crumbs.textContent).toContain("Employee Handbook");
    expect(screen.getByTestId("access-badge").textContent).toBe("Authenticated");
    expect(screen.getByTestId("data-handling").textContent).toBe("Local model only");
    expect(screen.getByTestId("collection-settings").textContent).toBe("Access & settings");
    const panel = screen.getByTestId("folders-panel");
    expect(panel.tagName).toBe("NAV");
    expect(panel.getAttribute("aria-label")).toBe("Folders");
    const rows = screen.getAllByTestId("folder-row");
    expect(rows.map((row) => row.getAttribute("data-depth"))).toEqual(["1", "2", "3"]);
    expect(rows.map((row) => row.getAttribute("data-folder-id"))).toEqual(["f1", "f2", "f3"]);
    expect(
      within(rows[0] as HTMLElement).getByRole("button", { name: "Rename Policies" }),
    ).toBeTruthy();
    expect(
      within(rows[0] as HTMLElement).getByRole("button", { name: "Delete Policies" }),
    ).toBeTruthy();
    expect(screen.getByTestId("documents-placeholder").textContent).toBe("No documents yet.");
    expect(screen.getByTestId("delete-collection-row").textContent).toContain(
      "Deletes the collection, its folders and everything indexed from it. This cannot be undone.",
    );
  });

  it("shows_no_folders_message", async () => {
    await open({}, makeDetail({ folders: [] }));
    expect(screen.getByTestId("folders-panel").textContent).toContain("No folders yet.");
  });

  it("hides_add_subfolder_at_depth_three", async () => {
    await open();
    const subfolder = (name: string) =>
      within(folderRow(name)).queryByRole("button", { name: `Add subfolder to ${name}` });
    expect(subfolder("Policies")).not.toBeNull();
    expect(subfolder("2026")).not.toBeNull();
    expect(subfolder("Q1")).toBeNull();
  });

  it("creates_nested_folder", async () => {
    const created = folder("f4", "Leave", 2, "f1");
    const { api } = await open({
      [`POST ${BASE}/c1/folders`]: () => json(201, created),
    });
    fireEvent.click(screen.getByRole("button", { name: "Add subfolder to Policies" }));
    const dialog = screen.getByTestId("folder-dialog");
    expect(within(dialog).getByRole("heading", { name: "New folder" })).toBeTruthy();
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Folder name" }), {
      target: { value: "  Leave " },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create folder" }));
    await waitFor(() => expect(screen.queryByTestId("folder-dialog")).toBeNull());
    const [call] = callsTo(api, `POST ${BASE}/c1/folders`);
    expect(JSON.parse(String(call?.body))).toEqual({ name: "Leave", parent_id: "f1" });
    const rows = screen.getAllByTestId("folder-row");
    expect(rows.map((row) => row.getAttribute("data-folder-id"))).toEqual(["f1", "f2", "f3", "f4"]);
    expect(folderRow("Leave").getAttribute("data-depth")).toBe("2");
  });

  it("creates_top_level_folder_and_reports_name_taken", async () => {
    const { api } = await open({
      [`POST ${BASE}/c1/folders`]: () => json(409, { detail: "name_taken" }),
    });
    fireEvent.click(screen.getByTestId("new-folder"));
    fireEvent.change(screen.getByRole("textbox", { name: "Folder name" }), {
      target: { value: "Policies" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create folder" }));
    const alert = await within(screen.getByTestId("folder-dialog")).findByRole("alert");
    expect(alert.textContent).toBe("A folder with this name already exists here.");
    const [call] = callsTo(api, `POST ${BASE}/c1/folders`);
    expect(JSON.parse(String(call?.body))).toEqual({ name: "Policies", parent_id: null });
  });

  it("renames_a_folder", async () => {
    const { api } = await open({
      [`PATCH ${BASE}/c1/folders/f1`]: () => json(200, folder("f1", "Rules", 1, null)),
    });
    fireEvent.click(screen.getByRole("button", { name: "Rename Policies" }));
    const input = screen.getByRole("textbox", { name: "Folder name" }) as HTMLInputElement;
    expect(input.value).toBe("Policies");
    expect(screen.getByRole("heading", { name: "Rename folder" })).toBeTruthy();
    fireEvent.change(input, { target: { value: "Rules" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByTestId("folder-dialog")).toBeNull());
    expect(JSON.parse(String(callsTo(api, `PATCH ${BASE}/c1/folders/f1`)[0]?.body))).toEqual({
      name: "Rules",
    });
    expect(folderRow("Rules")).toBeTruthy();
  });

  it("shows_folder_not_empty_message", async () => {
    await open({
      [`DELETE ${BASE}/c1/folders/f1`]: () => json(409, { detail: "folder_not_empty" }),
    });
    fireEvent.click(screen.getByRole("button", { name: "Delete Policies" }));
    const dialog = screen.getByTestId("confirm-folder-delete");
    expect(within(dialog).getByRole("heading", { name: "Delete folder?" })).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete folder" }));
    const alert = await within(dialog).findByRole("alert");
    expect(alert.textContent).toBe("Delete its subfolders first.");
    expect(screen.getAllByTestId("folder-row")).toHaveLength(3);
  });

  it("deletes_a_leaf_folder", async () => {
    await open({ [`DELETE ${BASE}/c1/folders/f3`]: () => new Response(null, { status: 204 }) });
    fireEvent.click(screen.getByRole("button", { name: "Delete Q1" }));
    fireEvent.click(
      within(screen.getByTestId("confirm-folder-delete")).getByRole("button", {
        name: "Delete folder",
      }),
    );
    await waitFor(() => expect(screen.getAllByTestId("folder-row")).toHaveLength(2));
    expect(screen.queryByTestId("confirm-folder-delete")).toBeNull();
  });

  it("updates_the_page_after_settings_are_saved", async () => {
    const item = { ...makeDetail({ name: "Handbook 2" }), folders: undefined };
    await open({ [`PATCH ${BASE}/c1`]: () => json(200, item) });
    fireEvent.click(screen.getByTestId("collection-settings"));
    const dialog = screen.getByTestId("collection-dialog");
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Name" }), {
      target: { value: "Handbook 2" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByTestId("collection-dialog")).toBeNull());
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Handbook 2");
    expect(screen.getByTestId("knowledge-status").textContent).toBe("Changes saved.");
    expect(screen.getAllByTestId("folder-row")).toHaveLength(3);
  });

  it("unknown_collection_shows_not_found", async () => {
    const session = {
      ...MULTI_SESSION,
      workspaces: [{ id: WS, name: "People Ops", role: "workspace_admin" }],
    };
    mockApi({
      ...signedInApi(session),
      [DETAIL]: () => json(404, { detail: "not_found" }),
    });
    renderAt(`/w/${WS}/knowledge/c1`);
    expect(await screen.findByTestId("not-found")).toBeTruthy();
    expect(screen.queryByTestId("collection-detail")).toBeNull();
  });

  it("malformed_collection_id_shows_not_found", async () => {
    const session = {
      ...MULTI_SESSION,
      workspaces: [{ id: WS, name: "People Ops", role: "workspace_admin" }],
    };
    mockApi({
      ...signedInApi(session),
      [`GET ${BASE}/abc`]: () => json(422, { detail: "invalid_request" }),
    });
    renderAt(`/w/${WS}/knowledge/abc`);
    expect(await screen.findByTestId("not-found")).toBeTruthy();
    expect(screen.queryByTestId("knowledge-error")).toBeNull();
  });

  it("delete_of_a_collection_deleted_elsewhere_shows_not_found", async () => {
    await open({ [`DELETE ${BASE}/c1`]: () => json(404, { detail: "not_found" }) });
    fireEvent.click(screen.getByTestId("delete-collection"));
    const dialog = screen.getByTestId("delete-collection-dialog");
    fireEvent.change(within(dialog).getByRole("textbox"), {
      target: { value: "Employee Handbook" },
    });
    fireEvent.click(within(dialog).getByTestId("confirm-delete-collection"));
    expect(await screen.findByTestId("not-found")).toBeTruthy();
  });

  it("folder_action_on_a_deleted_collection_shows_not_found", async () => {
    let gone = false;
    await open({
      [DETAIL]: () => (gone ? json(404, { detail: "not_found" }) : json(200, makeDetail())),
      [`DELETE ${BASE}/c1/folders/f3`]: () => {
        gone = true;
        return json(404, { detail: "not_found" });
      },
    });
    fireEvent.click(within(folderRow("Q1")).getByRole("button", { name: "Delete Q1" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete folder" }));
    expect(await screen.findByTestId("not-found")).toBeTruthy();
  });

  it("folder_404_with_the_collection_present_keeps_the_dialog_error", async () => {
    await open({
      [`DELETE ${BASE}/c1/folders/f3`]: () => json(404, { detail: "not_found" }),
    });
    fireEvent.click(within(folderRow("Q1")).getByRole("button", { name: "Delete Q1" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete folder" }));
    const alert = await within(screen.getByTestId("confirm-folder-delete")).findByRole("alert");
    expect(alert.textContent).toBe("Something went wrong. Try again.");
    expect(screen.queryByTestId("not-found")).toBeNull();
  });

  it("folder_delete_error_keeps_escape_and_focus_in_the_dialog", async () => {
    await open({
      [`DELETE ${BASE}/c1/folders/f1`]: () => json(409, { detail: "folder_not_empty" }),
    });
    const opener = within(folderRow("Policies")).getByRole("button", { name: "Delete Policies" });
    opener.focus();
    fireEvent.click(opener);
    const dialog = screen.getByTestId("confirm-folder-delete");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete folder" }));
    await within(dialog).findByRole("alert");
    expect(dialog.contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(document.activeElement as Element, { key: "Escape" });
    expect(screen.queryByTestId("confirm-folder-delete")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("delete_returns_to_list_with_status", async () => {
    const { router } = await open({
      [`DELETE ${BASE}/c1`]: () => new Response(null, { status: 204 }),
      [`GET ${BASE}`]: () => json(200, { collections: [] }),
    });
    fireEvent.click(screen.getByTestId("delete-collection"));
    const dialog = screen.getByTestId("delete-collection-dialog");
    fireEvent.change(
      within(dialog).getByRole("textbox", { name: "Type Employee Handbook to confirm" }),
      { target: { value: "Employee Handbook" } },
    );
    fireEvent.click(within(dialog).getByTestId("confirm-delete-collection"));
    await screen.findByTestId("knowledge-page");
    expect(router.state.location.pathname).toBe(`/w/${WS}/knowledge`);
    expect((await screen.findByTestId("knowledge-status")).textContent).toBe(
      "Employee Handbook was deleted.",
    );
  });

  it("delete_failure_stays_in_the_dialog", async () => {
    await open({ [`DELETE ${BASE}/c1`]: () => json(403, { detail: "forbidden" }) });
    fireEvent.click(screen.getByTestId("delete-collection"));
    const dialog = screen.getByTestId("delete-collection-dialog");
    fireEvent.change(within(dialog).getByRole("textbox"), {
      target: { value: "Employee Handbook" },
    });
    fireEvent.click(within(dialog).getByTestId("confirm-delete-collection"));
    const alert = await within(dialog).findByRole("alert");
    expect(alert.textContent).toBe("You don't have permission to do this.");
  });
});
