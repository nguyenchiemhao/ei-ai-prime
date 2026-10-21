import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createI18n } from "../i18n";
import { DeleteCollectionDialog } from "./DeleteCollectionDialog";

afterEach(cleanup);

function openDialog(name = "Employee Handbook") {
  const onConfirm = vi.fn();
  const onClose = vi.fn();
  render(
    <I18nextProvider i18n={createI18n()}>
      <DeleteCollectionDialog
        name={name}
        sending={false}
        error={null}
        onConfirm={onConfirm}
        onClose={onClose}
      />
    </I18nextProvider>,
  );
  const input = screen.getByRole("textbox", { name: `Type ${name} to confirm` });
  const confirm = screen.getByTestId("confirm-delete-collection") as HTMLButtonElement;
  return { input, confirm, onConfirm, onClose };
}

describe("DeleteCollectionDialog", () => {
  it("delete_requires_exact_name", () => {
    const { input, confirm, onConfirm } = openDialog();
    expect(screen.getByRole("heading", { name: "Delete Employee Handbook?" })).toBeTruthy();
    expect(confirm.disabled).toBe(true);
    for (const typed of ["employee handbook", "Employee", "Employee Handbook!"]) {
      fireEvent.change(input, { target: { value: typed } });
      expect(confirm.disabled).toBe(true);
    }
    fireEvent.change(input, { target: { value: "  Employee Handbook  " } });
    expect(confirm.disabled).toBe(false);
    fireEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("closes_on_cancel_and_escape_without_confirming", () => {
    const { input, onConfirm, onClose } = openDialog();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
