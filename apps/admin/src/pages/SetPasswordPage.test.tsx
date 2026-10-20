import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCsrfToken } from "../api/client";
import { callsTo, json, mockApi, renderAt } from "../test/renderApp";

const ANON = () => json(401, { detail: "unauthenticated" });
const TOKEN = "org-1.secret_Value-43";
const LONG_ENOUGH = "a-long-enough-password";
const INVALID_LINK =
  "This link is invalid or has expired. Ask your organization admin for a new link.";

beforeEach(() => clearCsrfToken());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

async function open(path: string, hash: string, extra: Parameters<typeof mockApi>[0] = {}) {
  window.history.replaceState(null, "", `${path}${hash}`);
  const api = mockApi({ "GET /auth/session": ANON, ...extra });
  const router = renderAt(path);
  await screen.findByRole("button", { name: "Set password" });
  return { api, router };
}

function fill(password: string, confirm: string) {
  fireEvent.change(screen.getByLabelText("New password"), { target: { value: password } });
  fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: confirm } });
}

function submit() {
  fireEvent.click(screen.getByRole("button", { name: "Set password" }));
}

describe("SetPasswordPage", () => {
  it("shows_the_set_copy_on_set_password", async () => {
    await open("/set-password", `#token=${TOKEN}`);

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Set your password");
    expect(document.title).toBe("Set your password · ei-ai");
    const field = screen.getByLabelText("New password") as HTMLInputElement;
    expect(field.type).toBe("password");
    expect(field.autocomplete).toBe("new-password");
    expect(screen.getByText("At least 12 characters.")).not.toBeNull();
    expect(field.getAttribute("aria-describedby")).toContain(
      screen.getByText("At least 12 characters.").id,
    );
    expect(screen.getByLabelText("Confirm password")).not.toBeNull();
  });

  it("shows_the_reset_title_on_reset", async () => {
    await open("/reset", `#token=${TOKEN}`);

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Reset your password");
    expect(document.title).toBe("Reset your password · ei-ai");
  });

  it("removes_the_fragment_from_the_address_bar", async () => {
    await open("/set-password", `#token=${TOKEN}`);

    await waitFor(() => expect(window.location.hash).toBe(""));
    expect(window.location.pathname).toBe("/set-password");
  });

  it.each(["/set-password", "/reset"])(
    "takes_the_token_of_a_link_opened_later_in_the_same_tab_on_%s",
    async (path) => {
      const { api } = await open(path, "#token=org-1.first_link_token", {
        "POST /auth/set-password": () => new Response(null, { status: 204 }),
      });
      await waitFor(() => expect(window.location.hash).toBe(""));
      fill(LONG_ENOUGH, `${LONG_ENOUGH}-different`);
      submit();
      expect(screen.getByText("The passwords do not match.")).not.toBeNull();

      // Only the fragment differs, so the browser does not reload the page.
      window.location.hash = `#token=${TOKEN}`;

      await waitFor(() => expect(window.location.hash).toBe(""));
      expect(window.location.pathname).toBe(path);
      expect((screen.getByLabelText("New password") as HTMLInputElement).value).toBe("");
      expect((screen.getByLabelText("Confirm password") as HTMLInputElement).value).toBe("");
      expect(screen.queryByText("The passwords do not match.")).toBeNull();
      fill(LONG_ENOUGH, LONG_ENOUGH);
      submit();
      await waitFor(() => expect(callsTo(api, "POST /auth/set-password")).toHaveLength(1));
      const [call] = callsTo(api, "POST /auth/set-password");
      expect(JSON.parse(String(call?.body))).toEqual({ token: TOKEN, password: LONG_ENOUGH });
    },
  );

  it("clears_the_invalid_link_alert_when_a_link_with_a_token_arrives", async () => {
    await open("/set-password", "");
    expect(screen.getByTestId("set-password-error").textContent).toBe(INVALID_LINK);

    window.location.hash = `#token=${TOKEN}`;

    await waitFor(() => expect(screen.queryByTestId("set-password-error")).toBeNull());
    await waitFor(() => expect(window.location.hash).toBe(""));
  });

  it("validates_length_and_match_without_a_request", async () => {
    const { api } = await open("/set-password", `#token=${TOKEN}`);

    fill("short", "short");
    submit();
    expect(screen.getByText("Use at least 12 characters.").getAttribute("role")).toBe("alert");

    fill("x".repeat(129), "x".repeat(129));
    submit();
    expect(screen.getByText("Use at most 128 characters.")).not.toBeNull();

    fill(LONG_ENOUGH, `${LONG_ENOUGH}-different`);
    submit();
    expect(screen.getByText("The passwords do not match.")).not.toBeNull();

    expect(callsTo(api, "POST /auth/set-password")).toHaveLength(0);
  });

  it("posts_the_token_and_goes_to_sign_in_with_the_notice", async () => {
    const { api, router } = await open("/set-password", `#token=${TOKEN}`, {
      "POST /auth/set-password": () => new Response(null, { status: 204 }),
    });

    fill(LONG_ENOUGH, LONG_ENOUGH);
    submit();

    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
    const [call] = callsTo(api, "POST /auth/set-password");
    expect(JSON.parse(String(call?.body))).toEqual({ token: TOKEN, password: LONG_ENOUGH });
    expect((await screen.findByTestId("sign-in-notice")).textContent).toBe(
      "Your password is set. Sign in to continue.",
    );
  });

  it("shows_the_invalid_link_message_on_400_invalid_token", async () => {
    await open("/set-password", `#token=${TOKEN}`, {
      "POST /auth/set-password": () => json(400, { detail: "invalid_token" }),
    });

    fill(LONG_ENOUGH, LONG_ENOUGH);
    submit();

    const alert = await screen.findByTestId("set-password-error");
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.textContent).toBe(INVALID_LINK);
  });

  it("shows_the_invalid_link_message_when_the_token_is_missing_and_sends_nothing", async () => {
    const { api } = await open("/set-password", "");

    expect(screen.getByTestId("set-password-error").textContent).toBe(INVALID_LINK);
    fill(LONG_ENOUGH, LONG_ENOUGH);
    submit();

    expect(callsTo(api, "POST /auth/set-password")).toHaveLength(0);
    expect(screen.getByTestId("set-password-error").textContent).toBe(INVALID_LINK);
  });

  it("shows_the_unavailable_message_on_a_network_error", async () => {
    await open("/set-password", `#token=${TOKEN}`, {
      "POST /auth/set-password": () => {
        throw new TypeError("offline");
      },
    });

    fill(LONG_ENOUGH, LONG_ENOUGH);
    submit();

    expect((await screen.findByTestId("set-password-error")).textContent).toBe(
      "The service is unavailable. Try again later.",
    );
  });
});
