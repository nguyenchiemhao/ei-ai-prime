import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { createI18n } from "./i18n";

function mockHealthz(response: Promise<Pick<Response, "ok" | "json">>) {
  const fetchMock = vi.fn().mockReturnValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderApp() {
  return render(
    <I18nextProvider i18n={createI18n()}>
      <App />
    </I18nextProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("renders_product_name_in_english_by_default", async () => {
    mockHealthz(Promise.resolve({ ok: true, json: async () => ({ status: "ok" }) }));

    renderApp();

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("ei-ai");
    expect(screen.getByText("Administration")).not.toBeNull();
    await screen.findByText("API: OK");
  });

  it("switches_to_vietnamese", async () => {
    mockHealthz(Promise.resolve({ ok: true, json: async () => ({ status: "ok" }) }));
    renderApp();
    await screen.findByText("API: OK");

    fireEvent.change(screen.getByLabelText("Language"), { target: { value: "vi" } });

    expect(screen.getByText("Quản trị")).not.toBeNull();
    expect(screen.getByLabelText("Ngôn ngữ")).not.toBeNull();
    expect(screen.getByText("API: hoạt động")).not.toBeNull();
    expect(document.documentElement.lang).toBe("vi");
  });

  it("shows_api_ok_when_healthz_returns_200", async () => {
    const fetchMock = mockHealthz(
      Promise.resolve({ ok: true, json: async () => ({ status: "ok" }) }),
    );

    renderApp();

    expect(await screen.findByText("API: OK")).not.toBeNull();
    expect(fetchMock).toHaveBeenCalledWith("/api/healthz", expect.anything());
  });

  it("shows_api_unavailable_when_request_fails", async () => {
    mockHealthz(Promise.reject(new TypeError("network down")));

    renderApp();

    expect(await screen.findByText("API: unavailable")).not.toBeNull();
  });

  it("shows_api_unavailable_when_healthz_returns_an_error_status", async () => {
    mockHealthz(Promise.resolve({ ok: false, json: async () => ({}) }));

    renderApp();

    expect(await screen.findByText("API: unavailable")).not.toBeNull();
  });
});
