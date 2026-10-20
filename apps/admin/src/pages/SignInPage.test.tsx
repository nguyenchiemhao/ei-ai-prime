import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCsrfToken } from "../api/client";
import { callsTo, json, mockApi, renderAt, SESSION, WS } from "../test/renderApp";

const ANON = () => json(401, { detail: "unauthenticated" });
const UNAVAILABLE = "The service is unavailable. Try again later.";

beforeEach(() => clearCsrfToken());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function fill(email: string, password: string) {
  fireEvent.change(screen.getByLabelText("Work email"), { target: { value: email } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
}

function submit() {
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

async function openSignIn(extra: Parameters<typeof mockApi>[0] = {}) {
  const api = mockApi({ "GET /auth/session": ANON, ...extra });
  const router = renderAt("/sign-in");
  await screen.findByTestId("sign-in-form");
  return { api, router };
}

describe("SignInPage", () => {
  it("matches_the_artboard_copy_and_resolves_labels", async () => {
    await openSignIn();

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Sign in");
    expect(screen.getByText("ei-ai")).not.toBeNull();
    expect(screen.getByText("Use and manage your organization's assistants.")).not.toBeNull();
    expect(screen.getByText("Accounts are created by your organization admin.")).not.toBeNull();
    const email = screen.getByLabelText("Work email") as HTMLInputElement;
    const password = screen.getByLabelText("Password") as HTMLInputElement;
    expect(email.type).toBe("email");
    expect(email.autocomplete).toBe("username");
    expect(password.type).toBe("password");
    expect(password.autocomplete).toBe("current-password");
    expect(screen.getByRole("link", { name: "Forgot password?" }).getAttribute("href")).toBe(
      "/forgot-password",
    );
    expect(screen.getByRole("button", { name: "Sign in" })).not.toBeNull();
    expect(screen.queryByText("Later")).toBeNull();
    expect(document.title).toBe("Sign in · ei-ai");
  });

  it("blocks_empty_fields_without_a_request", async () => {
    const { api } = await openSignIn();

    submit();

    const emailAlert = screen.getByText("Enter your email");
    expect(emailAlert.getAttribute("role")).toBe("alert");
    expect(screen.getByLabelText("Work email").getAttribute("aria-describedby")).toContain(
      emailAlert.id,
    );
    expect(screen.getByText("Enter your password")).not.toBeNull();
    expect(callsTo(api, "POST /auth/sign-in")).toHaveLength(0);
  });

  it("shows_a_generic_alert_and_clears_the_password_on_401", async () => {
    await openSignIn({ "POST /auth/sign-in": () => json(401, { detail: "invalid_credentials" }) });

    fill("a@x.test", "wrong-password");
    submit();

    const alert = await screen.findByTestId("sign-in-error");
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.textContent).toBe("Invalid email or password");
    expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe("");
    expect(screen.getByLabelText("Password").getAttribute("aria-describedby")).toContain(alert.id);
  });

  it("signs_in_and_opens_the_default_dashboard", async () => {
    let signedIn = false;
    const { api, router } = await openSignIn({
      "GET /auth/session": () => (signedIn ? json(200, SESSION) : ANON()),
      "POST /auth/sign-in": () => {
        signedIn = true;
        return json(200, { default_workspace_id: WS });
      },
    });

    fill("  a@x.test", "correct-password");
    submit();

    await waitFor(() => expect(router.state.location.pathname).toBe(`/w/${WS}/dashboard`));
    const [call] = callsTo(api, "POST /auth/sign-in");
    expect(JSON.parse(String(call?.body))).toEqual({
      email: "a@x.test",
      password: "correct-password",
    });
  });

  it("opens_no_workspace_when_there_is_no_default_workspace", async () => {
    let signedIn = false;
    const { router } = await openSignIn({
      "GET /auth/session": () =>
        signedIn ? json(200, { ...SESSION, workspaces: [], default_workspace_id: null }) : ANON(),
      "POST /auth/sign-in": () => {
        signedIn = true;
        return json(200, { default_workspace_id: null });
      },
    });

    fill("a@x.test", "correct-password");
    submit();

    await waitFor(() => expect(router.state.location.pathname).toBe("/no-workspace"));
  });

  it("shows_the_rate_limit_message_on_429", async () => {
    await openSignIn({ "POST /auth/sign-in": () => json(429, { detail: "rate_limited" }) });

    fill("a@x.test", "whatever-password");
    submit();

    expect((await screen.findByTestId("sign-in-error")).textContent).toBe(
      "Too many attempts. Wait a minute and try again.",
    );
    expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe("");
  });

  it("shows_the_unavailable_message_on_a_5xx", async () => {
    await openSignIn({ "POST /auth/sign-in": () => json(500, { detail: "boom" }) });

    fill("a@x.test", "whatever-password");
    submit();

    expect((await screen.findByTestId("sign-in-error")).textContent).toBe(UNAVAILABLE);
  });

  it("shows_the_unavailable_message_on_a_network_error", async () => {
    await openSignIn({
      "POST /auth/sign-in": () => {
        throw new TypeError("offline");
      },
    });

    fill("a@x.test", "whatever-password");
    submit();

    expect((await screen.findByTestId("sign-in-error")).textContent).toBe(UNAVAILABLE);
  });

  it("shows_the_password_set_notice_passed_by_the_set_password_page", async () => {
    const { router } = await openSignIn();
    expect(screen.queryByTestId("sign-in-notice")).toBeNull();

    await router.navigate("/sign-in", { state: { notice: "passwordSet" }, replace: true });

    const notice = await screen.findByTestId("sign-in-notice");
    expect(notice.getAttribute("role")).toBe("status");
    expect(notice.textContent).toBe("Your password is set. Sign in to continue.");
  });
});
