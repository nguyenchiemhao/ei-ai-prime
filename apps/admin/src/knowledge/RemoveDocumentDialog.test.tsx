import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCsrfToken } from "../api/client";
import type { DocumentItem } from "../api/documents";
import { createI18n } from "../i18n";
import { callsTo, json, mockApi } from "../test/renderApp";
import { RemoveDocumentDialog } from "./RemoveDocumentDialog";

const DELETE = "DELETE /workspaces/w1/collections/c1/documents/d1";
const DOCUMENT = { id: "d1", name: "broken.pdf" } as DocumentItem;

beforeEach(() => clearCsrfToken());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function setup(handlers: Parameters<typeof mockApi>[0] = {}) {
  const api = mockApi(handlers);
  const onRemoved = vi.fn();
  const onClose = vi.fn();
  const onSessionExpired = vi.fn();
  render(
    <I18nextProvider i18n={createI18n()}>
      <RemoveDocumentDialog
        workspaceId="w1"
        collectionId="c1"
        document={DOCUMENT}
        onRemoved={onRemoved}
        onClose={onClose}
        onSessionExpired={onSessionExpired}
      />
    </I18nextProvider>,
  );
  return { api, onRemoved, onClose, onSessionExpired };
}

describe("RemoveDocumentDialog", () => {
  it("remove_asks_confirmation_and_deletes", async () => {
    const { api, onRemoved } = setup({ [DELETE]: () => new Response(null, { status: 204 }) });
    expect(screen.getByRole("heading", { name: "Remove broken.pdf?" })).toBeTruthy();
    expect(screen.getByText("The file and its extracted text are deleted.")).toBeTruthy();
    expect(callsTo(api, DELETE)).toHaveLength(0);
    fireEvent.click(screen.getByTestId("confirm-remove-document"));
    await waitFor(() => expect(onRemoved).toHaveBeenCalledWith(DOCUMENT));
    expect(callsTo(api, DELETE)).toHaveLength(1);
  });

  it("cancel_sends_nothing", () => {
    const { api, onClose, onRemoved } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
    expect(onRemoved).not.toHaveBeenCalled();
    expect(callsTo(api, DELETE)).toHaveLength(0);
  });

  it("shows_an_error_and_stays_open_when_the_delete_fails", async () => {
    const { onRemoved } = setup({ [DELETE]: () => json(500, { detail: "internal" }) });
    fireEvent.click(screen.getByTestId("confirm-remove-document"));
    expect((await screen.findByRole("alert")).textContent).toBe("Something went wrong. Try again.");
    expect(onRemoved).not.toHaveBeenCalled();
  });

  it("treats_a_missing_document_as_removed", async () => {
    const { onRemoved } = setup({ [DELETE]: () => json(404, { detail: "not_found" }) });
    fireEvent.click(screen.getByTestId("confirm-remove-document"));
    await waitFor(() => expect(onRemoved).toHaveBeenCalledTimes(1));
  });

  it("ends_the_session_on_401", async () => {
    const { onRemoved, onSessionExpired } = setup({
      [DELETE]: () => json(401, { detail: "unauthenticated" }),
    });
    fireEvent.click(screen.getByTestId("confirm-remove-document"));
    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1));
    expect(onRemoved).not.toHaveBeenCalled();
  });
});
