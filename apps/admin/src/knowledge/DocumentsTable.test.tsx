import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { I18nextProvider } from "react-i18next";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DocumentItem } from "../api/documents";
import { createI18n } from "../i18n";
import { DocumentsTable } from "./DocumentsTable";

afterEach(cleanup);

const makeDocument = (extra: Partial<DocumentItem> = {}): DocumentItem => ({
  id: "d1",
  folder_id: "f1",
  name: "Overtime Policy 2026.pdf",
  format: "pdf",
  size_bytes: 1_258_291,
  status: "ready",
  progress: null,
  reason: null,
  page_count: 12,
  uploaded_by: { id: "u1", display_name: "Thao Nguyen" },
  created_at: "2026-10-02T09:00:00Z",
  updated_at: "2026-10-02T09:00:00Z",
  ...extra,
});

function renderTable(documents: DocumentItem[], inFolder = true) {
  const onPreview = vi.fn();
  const onRemove = vi.fn();
  render(
    <I18nextProvider i18n={createI18n()}>
      <DocumentsTable
        documents={documents}
        locale="en"
        inFolder={inFolder}
        onPreview={onPreview}
        onRemove={onRemove}
      />
    </I18nextProvider>,
  );
  return { onPreview, onRemove };
}

// Vitest does not load stylesheets, so the artboard rules are read from the file itself.
const styles = fs.readFileSync(path.resolve(__dirname, "knowledge.css"), "utf8");

const cell = (testId: string) => screen.getByTestId(testId).textContent;

describe("DocumentsTable", () => {
  it("renders_document_table_columns", () => {
    renderTable([makeDocument()]);
    const headers = within(screen.getByTestId("documents-table"))
      .getAllByRole("columnheader")
      .map((header) => header.textContent);
    expect(headers).toEqual(["Document", "Status", "Size", "Updated", "Actions"]);
    const row = screen.getByTestId("document-row");
    expect(row.getAttribute("data-document-id")).toBe("d1");
    expect(row.getAttribute("data-status")).toBe("ready");
    expect(cell("document-name")).toBe("Overtime Policy 2026.pdf");
    expect(cell("document-size")).toBe("1.2 MB");
    expect(cell("document-updated")).toBe("02 Oct · Thao Nguyen");
  });

  it("shows_today_yesterday_and_date_only_without_uploader", () => {
    const now = new Date();
    const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 12);
    renderTable([
      makeDocument({ id: "a", updated_at: now.toISOString() }),
      makeDocument({ id: "b", updated_at: yesterday.toISOString() }),
      makeDocument({ id: "c", uploaded_by: null }),
    ]);
    const updated = screen.getAllByTestId("document-updated").map((item) => item.textContent);
    expect(updated).toEqual(["Today · Thao Nguyen", "Yesterday · Thao Nguyen", "02 Oct"]);
  });

  it("shows_ready_with_page_count", () => {
    renderTable([makeDocument({ page_count: 3 }), makeDocument({ id: "d2", page_count: 1 })]);
    const statuses = screen.getAllByTestId("document-status").map((item) => item.textContent);
    expect(statuses).toEqual(["Ready · 3 pages", "Ready · 1 page"]);
    expect(screen.queryByTestId("document-reason")).toBeNull();
  });

  it("shows_processing_percent_without_actions", () => {
    renderTable([
      makeDocument({ id: "q", status: "queued", page_count: null }),
      makeDocument({ id: "p", status: "processing", progress: 60, page_count: null }),
    ]);
    const statuses = screen.getAllByTestId("document-status").map((item) => item.textContent);
    expect(statuses).toEqual(["Queued", "Processing · 60%"]);
    expect(screen.queryByTestId("preview-text")).toBeNull();
    expect(screen.queryByTestId("remove-document")).toBeNull();
  });

  it("shows_not_supported_with_ocr_message_and_remove", () => {
    const { onRemove } = renderTable([
      makeDocument({ status: "not_supported", reason: "scanned_pdf", page_count: null }),
    ]);
    expect(cell("document-status")).toBe("Not supported");
    expect(cell("document-reason")).toBe(
      "Scanned PDF without text. Text recognition (OCR) is planned for a later release.",
    );
    expect(screen.queryByTestId("preview-text")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Remove Overtime Policy 2026.pdf" }));
    expect(onRemove).toHaveBeenCalledTimes(1);
  });

  it("shows_failed_with_reason", () => {
    renderTable([
      makeDocument({ id: "a", status: "failed", reason: "corrupt_file", page_count: null }),
      makeDocument({ id: "b", status: "failed", reason: "interrupted", page_count: null }),
    ]);
    expect(screen.getAllByTestId("document-status").map((item) => item.textContent)).toEqual([
      "Failed",
      "Failed",
    ]);
    expect(screen.getAllByTestId("document-reason").map((item) => item.textContent)).toEqual([
      "The file could not be read. It may be damaged.",
      "Processing was interrupted. Remove the file and upload it again.",
    ]);
    expect(screen.getAllByTestId("remove-document")).toHaveLength(2);
  });

  it("preview_text_only_on_ready_rows", () => {
    const { onPreview } = renderTable([
      makeDocument({ id: "a" }),
      makeDocument({ id: "b", status: "failed", reason: "no_text", page_count: null }),
    ]);
    expect(screen.getAllByTestId("preview-text")).toHaveLength(1);
    fireEvent.click(
      screen.getByRole("button", { name: "Preview text of Overtime Policy 2026.pdf" }),
    );
    expect(onPreview).toHaveBeenCalledWith(expect.objectContaining({ id: "a" }));
    const failedRow = screen.getAllByTestId("document-row")[1] as HTMLElement;
    expect(within(failedRow).queryByTestId("preview-text")).toBeNull();
  });

  it("shows_empty_message", () => {
    const { unmount } = render(
      <I18nextProvider i18n={createI18n()}>
        <DocumentsTable
          documents={[]}
          locale="en"
          inFolder
          onPreview={vi.fn()}
          onRemove={vi.fn()}
        />
      </I18nextProvider>,
    );
    expect(cell("documents-empty")).toBe("No documents in this folder yet.");
    unmount();
    renderTable([], false);
    expect(cell("documents-empty")).toBe("No documents yet.");
    expect(screen.queryByTestId("documents-table")).toBeNull();
  });

  describe("matches_the_collection_detail_artboard", () => {
    it("shows_a_progress_bar_for_processing", () => {
      renderTable([makeDocument({ status: "processing", progress: 60, page_count: null })]);
      const bar = screen.getByTestId("document-progress");
      expect(bar.getAttribute("aria-hidden")).toBe("true");
      expect((bar.firstElementChild as HTMLElement).style.width).toBe("60%");
    });

    it("shows_no_progress_bar_for_other_statuses", () => {
      renderTable([makeDocument()]);
      expect(screen.queryByTestId("document-progress")).toBeNull();
    });

    it("renders_preview_and_remove_as_text_links", () => {
      renderTable([
        makeDocument(),
        makeDocument({ id: "d2", status: "failed", reason: "corrupt_file", page_count: null }),
      ]);
      expect(screen.getByTestId("preview-text").className).toBe("button-link");
      expect(screen.getByTestId("remove-document").className).toBe("button-link");
    });

    it("styles_statuses_rows_and_cells_with_design_tokens", () => {
      const rule = (selector: string) => {
        const start = styles.indexOf(`${selector} {`);
        expect(start, selector).toBeGreaterThanOrEqual(0);
        return styles.slice(start, styles.indexOf("}", start));
      };
      expect(rule('.document-status[data-status="ready"]')).toContain(
        "var(--ei-color-status-success-text)",
      );
      expect(rule('.document-status[data-status="processing"]')).toContain(
        "var(--ei-color-accent-default)",
      );
      expect(rule('.document-row[data-status="failed"]')).toContain(
        "var(--ei-color-surface-sensitive-row)",
      );
      expect(styles).toContain('.document-row[data-status="not_supported"],');
      expect(rule(".document-nowrap")).toContain("white-space: nowrap");
    });

    it("keeps_size_and_updated_on_one_line", () => {
      renderTable([makeDocument()]);
      expect(screen.getByTestId("document-size").className).toContain("document-nowrap");
      expect(screen.getByTestId("document-updated").className).toContain("document-nowrap");
    });

    it("keeps_the_actions_link_on_one_line", () => {
      renderTable([makeDocument()]);
      const actions = screen.getByTestId("preview-text").closest("td");
      expect(actions?.className).toContain("document-nowrap");
    });
  });
});
