import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCsrfToken } from "../api/client";
import type { CollectionItem } from "../api/collections";
import { MULTI_SESSION, signedInApi } from "../shell/shellTestKit";
import { json, mockApi, renderAt, WS } from "../test/renderApp";

beforeEach(() => clearCsrfToken());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function collection(
  id: string,
  name: string,
  level: string,
  extra: Partial<CollectionItem> = {},
): CollectionItem {
  return {
    id,
    name,
    subtitle: null,
    access_level: level,
    groups: [],
    local_only: false,
    documents: { total: 0, ready: 0, processing: 0, needs_attention: 0 },
    used_by: [],
    created_at: "2026-10-20T00:00:00Z",
    updated_at: "2026-10-20T00:00:00Z",
    ...extra,
  };
}

const ITEMS: CollectionItem[] = [
  collection("c1", "Company & Careers", "public"),
  collection("c2", "Employee Handbook", "authenticated"),
  collection("c3", "Manager Handbook", "restricted", { groups: ["managers"], local_only: true }),
  collection("c4", "Project Falcon", "restricted", {
    groups: ["project-falcon", "legal"],
    subtitle: "Client: Japan · under NDA",
    local_only: true,
  }),
  collection("c5", "Quỹ lương", "authenticated"),
];

async function open(items: CollectionItem[], role = "workspace_admin") {
  const session = {
    ...MULTI_SESSION,
    workspaces: [{ id: WS, name: "People Ops", role }],
  };
  mockApi({
    ...signedInApi(session),
    [`GET /workspaces/${WS}/collections`]: () => json(200, { collections: items }),
  });
  renderAt(`/w/${WS}/knowledge`);
  await screen.findByTestId("knowledge-page");
  await screen.findByTestId(items.length ? "collections-table" : "collections-empty");
}

const rows = () => screen.getAllByTestId("collection-row");

describe("KnowledgePage", () => {
  it("renders_artboard_columns_legend_and_footnote", async () => {
    await open(ITEMS);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Knowledge");
    expect(document.title).toBe("Knowledge · ei-ai");
    const page = screen.getByTestId("knowledge-page");
    expect(page.textContent).toContain(
      "Collections hold your documents. Access is set per collection and enforced before anything reaches the model.",
    );
    expect(
      within(screen.getByTestId("collections-table"))
        .getAllByRole("columnheader")
        .map((header) => header.textContent),
    ).toEqual(["Collection", "Who can read", "Data handling", "Documents", "Status", "Used by"]);
    const legend = screen.getByTestId("access-legend");
    expect(legend.textContent).toContain("Anyone, including anonymous visitors.");
    expect(legend.textContent).toContain("Any signed-in user of your app.");
    expect(legend.textContent).toContain(
      "Only people in one of the listed groups (from the widget token or Members & roles).",
    );
    expect(within(legend).getAllByTestId("access-badge")).toHaveLength(3);
    expect(screen.getByTestId("collections-footnote").textContent).toBe(
      "Only Workspace Admins can change who can read a collection. Making a collection Public asks for confirmation and is recorded in the audit log.",
    );
    expect(screen.getAllByRole("button", { name: "New collection" })).toHaveLength(1);
    expect(screen.getByTestId("collections-search")).not.toBeNull();
  });

  it("shows_created_row_with_badge_and_zero_documents", async () => {
    await open(ITEMS);
    const row = rows()[1] as HTMLElement;
    expect(row.getAttribute("data-collection-id")).toBe("c2");
    expect(within(row).getByRole("link", { name: "Employee Handbook" })).not.toBeNull();
    const badge = within(row).getByTestId("access-badge");
    expect(badge.textContent).toBe("Authenticated");
    expect(badge.getAttribute("data-access")).toBe("authenticated");
    expect(within(row).getByTestId("document-count").textContent).toBe("0");
    expect(within(row).getByTestId("collection-status").textContent).toBe("No documents");
    expect(within(row).getByTestId("used-by").textContent).toBe("Not used yet");
    expect(within(row).getByTestId("data-handling").textContent).toBe("Any allowed model");
  });

  it("shows_local_model_only_in_data_handling_and_the_subtitle_line", async () => {
    await open(ITEMS);
    const row = rows()[3] as HTMLElement;
    expect(within(row).getByTestId("data-handling").textContent).toBe("Local model only");
    expect(within(row).getByTestId("access-badge").textContent).toBe(
      "Restricted · project-falcon, legal",
    );
    expect(row.textContent).toContain("Client: Japan · under NDA");
  });

  it("badge_always_has_text", async () => {
    await open(ITEMS);
    for (const row of rows()) {
      const badge = within(row).getByTestId("access-badge");
      const level = badge.getAttribute("data-access") as string;
      expect((badge.textContent ?? "").toLowerCase()).toContain(level);
    }
  });

  it("shows_empty_state_with_single_new_collection_button", async () => {
    await open([]);
    expect(screen.getByTestId("collections-empty").textContent).toContain("No collections yet");
    expect(screen.getByTestId("collections-empty").textContent).toContain(
      "Create a collection to start adding documents.",
    );
    expect(screen.getAllByRole("button", { name: "New collection" })).toHaveLength(1);
    expect(screen.queryByTestId("collections-table")).toBeNull();
    expect(screen.queryByTestId("collections-search")).toBeNull();
    expect(screen.getByTestId("access-legend")).not.toBeNull();
    expect(screen.getByTestId("collections-footnote")).not.toBeNull();
  });

  it("filters_by_name_ignoring_diacritics", async () => {
    await open(ITEMS);
    fireEvent.change(screen.getByRole("textbox", { name: "Search collections" }), {
      target: { value: "quy luong" },
    });
    expect(rows().map((row) => row.getAttribute("data-collection-id"))).toEqual(["c5"]);
  });

  it("shows_no_match_message", async () => {
    await open(ITEMS);
    fireEvent.change(screen.getByRole("textbox", { name: "Search collections" }), {
      target: { value: "zzz" },
    });
    expect(screen.getByTestId("collections-no-match").textContent).toBe(
      "No collections match your search.",
    );
    expect(screen.queryByTestId("collection-row")).toBeNull();
  });

  it("shows_the_generic_alert_when_the_list_cannot_be_loaded", async () => {
    mockApi({
      ...signedInApi(),
      [`GET /workspaces/${WS}/collections`]: () => json(500, { detail: "internal_error" }),
    });
    renderAt(`/w/${WS}/knowledge`);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Something went wrong. Try again.");
    expect(alert.getAttribute("data-testid")).toBe("knowledge-error");
  });

  it("creates_a_collection_adds_the_row_and_shows_the_status", async () => {
    const created = collection("c9", "Aardvark Facts", "authenticated");
    await open(ITEMS);
    mockApi({
      ...signedInApi({
        ...MULTI_SESSION,
        workspaces: [{ id: WS, name: "People Ops", role: "workspace_admin" }],
      }),
      [`GET /workspaces/${WS}/collections`]: () => json(200, { collections: ITEMS }),
      [`POST /workspaces/${WS}/collections`]: () => json(201, created),
    });
    fireEvent.click(screen.getByTestId("new-collection"));
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Aardvark Facts" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create collection" }));
    const status = await screen.findByTestId("knowledge-status");
    expect(status.textContent).toBe("Aardvark Facts was created.");
    expect(screen.queryByTestId("collection-dialog")).toBeNull();
    expect(rows()[0]?.getAttribute("data-collection-id")).toBe("c9");
  });
});
