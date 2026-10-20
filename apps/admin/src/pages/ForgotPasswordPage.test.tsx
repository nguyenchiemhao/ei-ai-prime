import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCsrfToken } from "../api/client";
import { callsTo, json, mockApi, renderAt } from "../test/renderApp";

const ANON = () => json(401, { detail: "unauthenticated" });

beforeEach(() => clearCsrfToken());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function open(extra: Parameters<typeof mockApi>[0] = {}) {
  const api = mockApi({ "GET /auth/session": ANON, ...extra });
  renderAt("/forgot-password");
  await screen.findByRole("button", { name: "Send reset link" });
  return api;
}

describe("ForgotPasswordPage", () => {
  it("shows_the_copy_and_the_labelled_email_field", async () => {
    await open();

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Forgot password");
    expect(
      screen.getByText("Enter your work email. We will send you a link to set a new password."),
    ).not.toBeNull();
    const email = screen.getByLabelText("Work email") as HTMLInputElement;
    expect(email.type).toBe("email");
    expect(email.autocomplete).toBe("username");
    expect(screen.getByRole("link", { name: "Back to sign in" }).getAttribute("href")).toBe(
      "/sign-in",
    );
    expect(document.title).toBe("Forgot password · ei-ai");
  });

  it("blocks_an_empty_email_without_a_request", async () => {
    const api = await open();

    fireEvent.click(screen.getByRole("button", { name: "Send reset link" }));

    expect(screen.getByText("Enter your email")).not.toBeNull();
    expect(callsTo(api, "POST /auth/forgot-password")).toHaveLength(0);
  });

  it("shows_the_same_confirmation_for_any_email", async () => {
    const api = await open({
      "POST /auth/forgot-password": () => new Response(null, { status: 202 }),
    });

    fireEvent.change(screen.getByLabelText("Work email"), { target: { value: "Nobody@x.test" } });
    fireEvent.click(screen.getByRole("button", { name: "Send reset link" }));

    const confirmation = await screen.findByTestId("forgot-password-confirmation");
    expect(confirmation.textContent).toBe(
      "If an account exists for this email, a reset link has been sent.",
    );
    expect(confirmation.getAttribute("role")).toBe("status");
    const [call] = callsTo(api, "POST /auth/forgot-password");
    expect(JSON.parse(String(call?.body))).toEqual({ email: "Nobody@x.test" });
  });

  it("shows_the_rate_limit_message_on_429", async () => {
    await open({ "POST /auth/forgot-password": () => json(429, { detail: "rate_limited" }) });

    fireEvent.change(screen.getByLabelText("Work email"), { target: { value: "a@x.test" } });
    fireEvent.click(screen.getByRole("button", { name: "Send reset link" }));

    expect((await screen.findByRole("alert")).textContent).toBe(
      "Too many attempts. Wait a minute and try again.",
    );
    expect(screen.queryByTestId("forgot-password-confirmation")).toBeNull();
  });

  it("shows_the_unavailable_message_on_a_network_error", async () => {
    await open({
      "POST /auth/forgot-password": () => {
        throw new TypeError("offline");
      },
    });

    fireEvent.change(screen.getByLabelText("Work email"), { target: { value: "a@x.test" } });
    fireEvent.click(screen.getByRole("button", { name: "Send reset link" }));

    expect((await screen.findByRole("alert")).textContent).toBe(
      "The service is unavailable. Try again later.",
    );
  });
});
