import { cleanup, render, screen } from "@testing-library/preact";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("App", () => {
  it("greets_in_vietnamese_when_browser_language_is_vi", () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("vi-VN");

    render(<App />);

    expect(screen.getByText("Xin chào! Tôi có thể giúp gì cho bạn hôm nay?")).not.toBeNull();
    expect(document.documentElement.lang).toBe("vi");
  });

  it("greets_in_english_otherwise", () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("en-GB");

    render(<App />);

    expect(screen.getByText("Hello! How can I help you today?")).not.toBeNull();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("ei-ai");
  });

  it("has_a_polite_live_region_for_the_conversation", () => {
    render(<App />);

    const region = screen.getByRole("log", { name: "Conversation" });
    expect(region.getAttribute("aria-live")).toBe("polite");
  });
});
