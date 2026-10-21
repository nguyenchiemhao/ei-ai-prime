import en from "@ei-ai/i18n/en.json";
import { cleanup, render, screen, within } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { I18nextProvider } from "react-i18next";
import { afterEach, describe, expect, it } from "vitest";
import { createI18n } from "../i18n";
import { MATRIX_ROLES, ROLE_MATRIX } from "./matrixData";
import { RoleMatrix } from "./RoleMatrix";

afterEach(cleanup);

const RBAC_DOC = path.resolve(__dirname, "../../../../docs/architecture/rbac.md");

function label(key: string): string {
  const value = key
    .split(".")
    .reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], en);
  if (typeof value !== "string") throw new Error(`no English text for ${key}`);
  return value;
}

function renderMatrix() {
  render(
    <I18nextProvider i18n={createI18n()}>
      <RoleMatrix />
    </I18nextProvider>,
  );
  return screen.getByRole("table", { name: "What each role can do" });
}

describe("RoleMatrix", () => {
  it("is_a_table_named_by_its_heading_with_the_seven_column_headers", () => {
    const table = renderMatrix();
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("What each role can do");
    expect(table.getAttribute("data-testid")).toBe("role-matrix");
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((header) => header.textContent),
    ).toEqual([
      "Permission",
      "Admin",
      "Developer",
      "Builder",
      "Knowledge Editor",
      "Reviewer",
      "Viewer",
    ]);
  });

  it("has_the_eight_rows_of_the_artboard_in_order_with_the_exact_grid", () => {
    renderMatrix();
    const rows = screen.getAllByTestId("matrix-row");
    const grid = rows.map((row) => [
      row.getAttribute("data-permission"),
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ]);
    expect(grid).toEqual([
      ["knowledge.manage", ["Documents, scripts, glossary", "Yes", "—", "Yes", "Yes", "—", "—"]],
      ["assistants.manage", ["Assistants, skills, channels", "Yes", "—", "Yes", "—", "—", "—"]],
      [
        "playground.use",
        ["Playground (test drafts, see traces)", "Yes", "—", "Yes", "—", "—", "—"],
      ],
      ["assistants.publish", ["Publish an assistant", "Yes", "—", "Yes", "—", "—", "—"]],
      [
        "connectors.manage",
        ["Connectors, secrets, signing keys", "Yes", "Yes", "—", "—", "—", "—"],
      ],
      ["conversations.read", ["Read conversations", "—", "—", "—", "—", "Yes", "—"]],
      [
        "collections.access.manage",
        ["Change who can read a collection", "Yes", "—", "—", "—", "—", "—"],
      ],
      ["dashboard.view", ["Dashboard", "Yes", "Yes", "Yes", "Yes", "Yes", "Yes"]],
    ]);
  });

  it("marks_exactly_the_three_sensitive_rows", () => {
    renderMatrix();
    const sensitive = screen
      .getAllByTestId("matrix-row")
      .filter((row) => row.getAttribute("data-sensitive") === "true")
      .map((row) => row.getAttribute("data-permission"));
    expect(sensitive).toEqual(["assistants.publish", "connectors.manage", "conversations.read"]);
  });

  it("hides_the_dash_from_screen_readers_and_names_the_cell_no", () => {
    renderMatrix();
    const row = screen.getByRole("row", { name: /Read conversations/ });
    const noCells = within(row).getAllByRole("cell", { name: "No" });
    expect(noCells).toHaveLength(5);
    for (const cell of noCells) {
      expect(cell.querySelector('[aria-hidden="true"]')?.textContent).toBe("—");
    }
    expect(within(row).getAllByRole("cell", { name: "Yes" })).toHaveLength(1);
  });

  it("shows_the_footnote", () => {
    renderMatrix();
    expect(screen.getByTestId("role-matrix-note").textContent).toBe(
      "Highlighted rows are sensitive and kept in separate roles. Admins who need to read conversations assign themselves Reviewer; that change is recorded in the audit log.",
    );
  });

  it("equals_the_matrix_documented_in_docs_architecture_rbac_md", () => {
    const doc = fs.readFileSync(RBAC_DOC, "utf8");
    const block = /<!-- rbac-matrix:start -->\n([\s\S]*?)<!-- rbac-matrix:end -->/.exec(doc)?.[1];
    expect(block).toBeDefined();
    const [header, , ...body] = (block ?? "")
      .trim()
      .split("\n")
      .map((line) =>
        line
          .trim()
          .replace(/^\||\|$/g, "")
          .split("|")
          .map((cell) => cell.trim()),
      );
    expect(header).toEqual([
      "Permission",
      "Code",
      "Admin",
      "Developer",
      "Builder",
      "Knowledge Editor",
      "Reviewer",
      "Viewer",
    ]);
    expect(MATRIX_ROLES).toHaveLength(6);
    expect(body).toEqual(
      ROLE_MATRIX.map((row) => [
        label(row.labelKey),
        `\`${row.permission}\``,
        ...row.grants.map((granted) => (granted ? "Yes" : "—")),
      ]),
    );
  });
});
