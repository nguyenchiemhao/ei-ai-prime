import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCsrfToken } from "../api/client";
import type { CollectionItem } from "../api/collections";
import { createI18n } from "../i18n";
import { callsTo, json, mockApi, WS } from "../test/renderApp";
import { CollectionDialog } from "./CollectionDialog";

beforeEach(() => clearCsrfToken());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const CREATE = `POST /workspaces/${WS}/collections`;
const PATCH = `PATCH /workspaces/${WS}/collections/c1`;
const ACCESS = `PUT /workspaces/${WS}/collections/c1/access`;

function makeCollection(extra: Partial<CollectionItem> = {}): CollectionItem {
  return {
    id: "c1",
    name: "Handbook",
    subtitle: null,
    access_level: "authenticated",
    groups: [],
    local_only: false,
    documents: { total: 0, ready: 0, processing: 0, needs_attention: 0 },
    used_by: [],
    created_at: "2026-10-20T00:00:00Z",
    updated_at: "2026-10-20T00:00:00Z",
    ...extra,
  };
}

interface Options {
  mode?: "create" | "edit";
  collection?: CollectionItem;
  canManageAccess?: boolean;
  handlers?: Parameters<typeof mockApi>[0];
}

function openDialog({
  mode = "create",
  collection,
  canManageAccess = true,
  handlers = {},
}: Options = {}) {
  const api = mockApi(handlers);
  const onClose = vi.fn();
  const onSaved = vi.fn();
  const onSessionExpired = vi.fn();
  render(
    <I18nextProvider i18n={createI18n()}>
      <CollectionDialog
        mode={mode}
        workspaceId={WS}
        collection={collection}
        canManageAccess={canManageAccess}
        onClose={onClose}
        onSaved={onSaved}
        onSessionExpired={onSessionExpired}
      />
    </I18nextProvider>,
  );
  return { api, onClose, onSaved, onSessionExpired };
}

const radio = (name: string) => screen.getByRole("radio", { name }) as HTMLInputElement;
const submit = (name: string) => fireEvent.click(screen.getByRole("button", { name }));
const body = (api: ReturnType<typeof mockApi>, key: string) =>
  JSON.parse(String(callsTo(api, key)[0]?.body));

function fillName(value: string) {
  fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value } });
}

function fillGroups(value: string) {
  fireEvent.change(screen.getByRole("textbox", { name: "Groups" }), { target: { value } });
}

describe("CollectionDialog", () => {
  it("blocks_restricted_without_group", () => {
    const { api } = openDialog();
    fillName("Policies");
    fireEvent.click(radio("Restricted"));
    fillGroups(" , ,");
    submit("Create collection");
    expect(screen.getByTestId("groups-error").textContent).toBe("At least one group is required");
    expect(callsTo(api, CREATE)).toHaveLength(0);
    const groups = screen.getByRole("textbox", { name: "Groups" });
    expect(screen.getByRole("alert").textContent).toBe("At least one group is required");
    expect(groups.getAttribute("aria-describedby")).toContain(
      screen.getByTestId("groups-error").id,
    );
    expect(document.activeElement).toBe(groups);
  });

  it("maps_groups_required_from_api", async () => {
    const { api } = openDialog({
      handlers: { [CREATE]: () => json(422, { detail: "groups_required" }) },
    });
    fillName("Policies");
    fireEvent.click(radio("Restricted"));
    fillGroups("managers");
    submit("Create collection");
    await screen.findByTestId("groups-error");
    expect(callsTo(api, CREATE)).toHaveLength(1);
    expect(screen.getByTestId("groups-error").textContent).toBe("At least one group is required");
  });

  it("creates_authenticated_by_default_and_sends_groups_only_when_restricted", async () => {
    const created = makeCollection({ name: "Policies" });
    const { api, onSaved } = openDialog({
      handlers: { [CREATE]: () => json(201, created) },
    });
    expect(radio("Authenticated").checked).toBe(true);
    fillName(" Policies ");
    fireEvent.click(radio("Restricted"));
    fillGroups("Managers, legal ,");
    fireEvent.click(radio("Authenticated"));
    submit("Create collection");
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(created));
    expect(body(api, CREATE)).toEqual({
      name: "Policies",
      subtitle: null,
      access_level: "authenticated",
      groups: [],
      local_only: false,
    });
  });

  it("disables_access_controls_without_access_permission", () => {
    openDialog({
      mode: "edit",
      collection: makeCollection({ access_level: "restricted", groups: ["managers"] }),
      canManageAccess: false,
    });
    for (const name of ["Public", "Authenticated", "Restricted"]) {
      expect(radio(name).disabled).toBe(true);
    }
    expect((screen.getByRole("textbox", { name: "Groups" }) as HTMLInputElement).disabled).toBe(
      true,
    );
    expect(screen.getByTestId("access-locked-note").textContent).toBe(
      "Only Workspace Admins can change who can read a collection.",
    );
  });

  it("disables_public_option_on_create_without_access_permission", () => {
    openDialog({ canManageAccess: false });
    expect(radio("Public").disabled).toBe(true);
    expect(radio("Authenticated").disabled).toBe(false);
    expect(radio("Restricted").disabled).toBe(false);
    expect(screen.queryByTestId("access-locked-note")).toBeNull();
  });

  it("cannot_untick_local_only_without_access_permission", () => {
    openDialog({
      mode: "edit",
      collection: makeCollection({ local_only: true }),
      canManageAccess: false,
    });
    const box = screen.getByRole("checkbox", { name: "Local model only" }) as HTMLInputElement;
    expect(box.checked).toBe(true);
    expect(box.disabled).toBe(true);
  });

  it("asks_confirmation_before_making_public", async () => {
    const created = makeCollection({ name: "Open", access_level: "public" });
    const { api, onSaved } = openDialog({
      handlers: { [CREATE]: () => json(201, created) },
    });
    fillName("Open");
    fireEvent.click(radio("Public"));
    submit("Create collection");
    const confirm = screen.getByTestId("confirm-public-dialog");
    expect(confirm.textContent).toContain("Make this collection Public?");
    expect(confirm.textContent).toContain(
      "Anyone, including anonymous visitors, can get answers from its documents. This change is recorded in the audit log.",
    );
    expect(callsTo(api, CREATE)).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Make public" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(created));
    expect(body(api, CREATE).access_level).toBe("public");
  });

  it("cancel_public_sends_nothing", () => {
    const { api } = openDialog();
    fillName("Open");
    fireEvent.click(radio("Public"));
    submit("Create collection");
    const confirm = screen.getByTestId("confirm-public-dialog");
    fireEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByTestId("confirm-public-dialog")).toBeNull();
    expect(screen.getByTestId("collection-dialog")).toBeTruthy();
    expect(callsTo(api, CREATE)).toHaveLength(0);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Create collection" }));
  });

  it("escape_returns_focus_to_the_opener", () => {
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    const { onClose } = openDialog();
    fireEvent.keyDown(screen.getByTestId("collection-dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    cleanup();
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });

  it("no_confirmation_when_already_public", async () => {
    const existing = makeCollection({ access_level: "public" });
    const { api, onSaved } = openDialog({
      mode: "edit",
      collection: existing,
      handlers: { [PATCH]: () => json(200, { ...existing, name: "Renamed" }) },
    });
    fillName("Renamed");
    submit("Save");
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(screen.queryByTestId("confirm-public-dialog")).toBeNull();
    expect(callsTo(api, ACCESS)).toHaveLength(0);
  });

  it("edit_sends_access_only_when_changed", async () => {
    const existing = makeCollection({ access_level: "restricted", groups: ["managers"] });
    const renamed = { ...existing, name: "Renamed" };
    const regrouped = { ...existing, groups: ["managers", "legal"] };
    const first = openDialog({
      mode: "edit",
      collection: existing,
      handlers: { [PATCH]: () => json(200, renamed) },
    });
    fillName("Renamed");
    submit("Save");
    await waitFor(() => expect(first.onSaved).toHaveBeenCalledWith(renamed));
    expect(body(first.api, PATCH)).toEqual({ name: "Renamed" });
    expect(callsTo(first.api, ACCESS)).toHaveLength(0);

    cleanup();
    const second = openDialog({
      mode: "edit",
      collection: existing,
      handlers: { [ACCESS]: () => json(200, regrouped) },
    });
    fillGroups("Managers, legal");
    submit("Save");
    await waitFor(() => expect(second.onSaved).toHaveBeenCalledWith(regrouped));
    expect(body(second.api, ACCESS)).toEqual({
      access_level: "restricted",
      groups: ["Managers", "legal"],
    });
    expect(callsTo(second.api, PATCH)).toHaveLength(0);
  });

  it("escape_closes", () => {
    const { api, onClose } = openDialog();
    fireEvent.keyDown(screen.getByTestId("collection-dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(api).not.toHaveBeenCalled();
  });

  it("partial_save_reports_server_state_on_close", async () => {
    const existing = makeCollection();
    const patched = { ...existing, name: "Renamed" };
    const { api, onSaved, onClose } = openDialog({
      mode: "edit",
      collection: existing,
      handlers: {
        [PATCH]: () => json(200, patched),
        [ACCESS]: () => json(403, { detail: "forbidden" }),
      },
    });
    fillName("Renamed");
    fireEvent.click(radio("Restricted"));
    fillGroups("managers");
    submit("Save");
    await screen.findByRole("alert");
    expect(onSaved).not.toHaveBeenCalled();
    submit("Save");
    await waitFor(() => expect(callsTo(api, ACCESS)).toHaveLength(2));
    expect(callsTo(api, PATCH)).toHaveLength(1);
    submit("Cancel");
    expect(onSaved).toHaveBeenCalledWith(patched);
    expect(onClose).not.toHaveBeenCalled();
  });
});
