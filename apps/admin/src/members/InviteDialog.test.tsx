import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCsrfToken } from "../api/client";
import { createI18n } from "../i18n";
import { callsTo, json, mockApi, WS } from "../test/renderApp";
import { InviteDialog } from "./InviteDialog";

beforeEach(() => clearCsrfToken());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const INVITE = `POST /workspaces/${WS}/members`;
const CREATED = {
  user_id: "u9",
  display_name: "Ann",
  email: "ann@x.test",
  role: "viewer",
  org_role: null,
  last_active_at: null,
};

function openDialog(handlers: Parameters<typeof mockApi>[0] = {}) {
  const api = mockApi(handlers);
  const onClose = vi.fn();
  const onInvited = vi.fn();
  const onSessionExpired = vi.fn();
  render(
    <I18nextProvider i18n={createI18n()}>
      <InviteDialog
        workspaceId={WS}
        onClose={onClose}
        onInvited={onInvited}
        onSessionExpired={onSessionExpired}
      />
    </I18nextProvider>,
  );
  return {
    api,
    onClose,
    onInvited,
    onSessionExpired,
    dialog: screen.getByRole("dialog", { name: "Invite member" }),
  };
}

function fillAndSend(email: string) {
  fireEvent.change(screen.getByRole("textbox", { name: "Email" }), { target: { value: email } });
  fireEvent.click(screen.getByRole("button", { name: "Send invite" }));
}

describe("InviteDialog", () => {
  it("has_email_name_and_role_fields_with_viewer_as_default_and_focuses_the_email", () => {
    const { dialog } = openDialog();
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(document.activeElement).toBe(within(dialog).getByRole("textbox", { name: "Email" }));
    expect(within(dialog).getByRole("textbox", { name: "Name (optional)" })).not.toBeNull();
    const role = within(dialog).getByRole("combobox", { name: "Role" }) as HTMLSelectElement;
    expect(role.value).toBe("viewer");
    expect(
      within(role)
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
    expect(within(dialog).getByRole("button", { name: "Send invite" })).not.toBeNull();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).not.toBeNull();
  });

  it("sends_email_trimmed_name_and_role_and_reports_the_new_member", async () => {
    const { api, onInvited } = openDialog({ [INVITE]: () => json(201, CREATED) });
    fireEvent.change(screen.getByRole("textbox", { name: "Name (optional)" }), {
      target: { value: "  Ann  " },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Role" }), {
      target: { value: "builder" },
    });
    fillAndSend("ann@x.test");
    await waitFor(() => expect(onInvited).toHaveBeenCalledWith(CREATED));
    const [call] = callsTo(api, INVITE);
    expect(JSON.parse(String(call?.body))).toEqual({
      email: "ann@x.test",
      display_name: "Ann",
      role: "builder",
    });
  });

  it("leaves_the_name_out_when_it_is_blank", async () => {
    const { api, onInvited } = openDialog({ [INVITE]: () => json(201, CREATED) });
    fireEvent.change(screen.getByRole("textbox", { name: "Name (optional)" }), {
      target: { value: "   " },
    });
    fillAndSend("ann@x.test");
    await waitFor(() => expect(onInvited).toHaveBeenCalled());
    const [call] = callsTo(api, INVITE);
    expect(JSON.parse(String(call?.body))).toEqual({ email: "ann@x.test", role: "viewer" });
  });

  it("shows_the_invalid_email_alert_on_422_and_stays_open", async () => {
    const { onInvited, onClose } = openDialog({
      [INVITE]: () => json(422, { detail: "invalid_request" }),
    });
    fillAndSend("not-an-email");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Enter a valid email address.");
    expect(onInvited).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("shows_the_already_a_member_alert_on_409", async () => {
    openDialog({ [INVITE]: () => json(409, { detail: "already_member" }) });
    fillAndSend("ann@x.test");
    expect((await screen.findByRole("alert")).textContent).toBe(
      "This person is already a member of this workspace.",
    );
  });

  it("shows_the_forbidden_and_generic_alerts", async () => {
    openDialog({ [INVITE]: () => json(403, { detail: "forbidden" }) });
    fillAndSend("ann@x.test");
    expect((await screen.findByRole("alert")).textContent).toBe(
      "You don't have permission to do this.",
    );
    cleanup();
    vi.unstubAllGlobals();
    clearCsrfToken();

    openDialog({ [INVITE]: () => json(500, { detail: "internal_error" }) });
    fillAndSend("ann@x.test");
    expect((await screen.findByRole("alert")).textContent).toBe("Something went wrong. Try again.");
  });

  it("clears_an_old_alert_when_the_next_attempt_starts", async () => {
    let attempt = 0;
    openDialog({
      [INVITE]: () => {
        attempt += 1;
        return attempt === 1 ? json(422, { detail: "invalid_request" }) : json(201, CREATED);
      },
    });
    fillAndSend("bad");
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Send invite" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("closes_with_cancel_and_with_escape", () => {
    const { onClose, dialog } = openDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("keeps_tab_inside_the_dialog", () => {
    const { dialog } = openDialog();
    const send = within(dialog).getByRole("button", { name: "Send invite" });
    send.focus();
    fireEvent.keyDown(send, { key: "Tab" });
    expect(document.activeElement).toBe(within(dialog).getByRole("textbox", { name: "Email" }));
    fireEvent.keyDown(document.activeElement as Element, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(send);
  });

  it("limits_the_name_to_200_characters", () => {
    openDialog();
    expect(screen.getByRole("textbox", { name: "Name (optional)" }).getAttribute("maxlength")).toBe(
      "200",
    );
  });

  it("does_not_blame_the_email_when_a_well_formed_email_is_refused_with_422", async () => {
    openDialog({ [INVITE]: () => json(422, { detail: "invalid_request" }) });
    fillAndSend("ann@x.test");
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Check the email address and the name (up to 200 characters).",
    );
  });

  it("tells_the_shell_the_session_ended_on_401_instead_of_showing_an_alert", async () => {
    const { onSessionExpired } = openDialog({
      [INVITE]: () => json(401, { detail: "unauthenticated" }),
    });
    fillAndSend("ann@x.test");
    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
