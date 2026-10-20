import { cleanup, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCsrfToken } from "../api/client";
import { json, mockApi, renderAt } from "../test/renderApp";

beforeEach(() => clearCsrfToken());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("NotFoundPage", () => {
  it("shows_the_copy_title_and_a_link_to_the_dashboard", async () => {
    mockApi({ "GET /auth/session": () => json(401, { detail: "unauthenticated" }) });
    renderAt("/nope/nothing");
    const page = await screen.findByTestId("not-found");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Page not found");
    expect(page.textContent).toContain("This page does not exist or you do not have access to it.");
    expect(screen.getByRole("link", { name: "Go to your dashboard" }).getAttribute("href")).toBe(
      "/",
    );
    expect(document.title).toBe("Page not found · ei-ai");
  });
});
