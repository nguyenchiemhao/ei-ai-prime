import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AskEvent, AskRequest } from "../api/ask";
import { askCollection } from "../api/ask";
import type { ApiResult } from "../api/client";
import type { CollectionDetail } from "../api/collections";
import { createI18n, type Language } from "../i18n";
import { AskPanel } from "./AskPanel";

vi.mock("../api/ask", () => ({ askCollection: vi.fn() }));

const ask = vi.mocked(askCollection);
const OK: ApiResult<void> = { ok: true, data: undefined };

const PASSAGES: AskEvent = {
  type: "passages",
  language: "en",
  passages: [
    { number: 1, title: "Leave Policy 2026", section: "§4.1 Personal leave", page: 3, score: 0.91 },
    { number: 2, title: "Handbook", section: null, page: null, score: 0.5 },
  ],
};

function makeCollection(extra: Partial<CollectionDetail> = {}): CollectionDetail {
  return {
    id: "c1",
    name: "Handbook",
    subtitle: null,
    access_level: "authenticated",
    groups: [],
    local_only: true,
    documents: { total: 0, ready: 0, processing: 0, needs_attention: 0 },
    used_by: [],
    created_at: "2026-10-20T00:00:00Z",
    updated_at: "2026-10-20T00:00:00Z",
    folders: [],
    ...extra,
  };
}

// Makes askCollection replay the events, then resolve with the result.
function script(events: AskEvent[], result: ApiResult<void> = OK) {
  ask.mockImplementation((_w, _c, _r, onEvent) => {
    for (const event of events) onEvent(event);
    return Promise.resolve(result);
  });
}

function renderPanel(
  collection = makeCollection(),
  language: Language = "en",
  handlers: { onSessionExpired?: () => void; onNotFound?: () => void } = {},
) {
  const props = { onSessionExpired: vi.fn(), onNotFound: vi.fn(), ...handlers };
  const view = render(
    <I18nextProvider i18n={createI18n(language)}>
      <AskPanel workspaceId="w1" collection={collection} {...props} />
    </I18nextProvider>,
  );
  return { ...props, ...view };
}

function submit(question = "How many days?") {
  fireEvent.change(screen.getByTestId("ask-question"), { target: { value: question } });
  fireEvent.click(screen.getByTestId("ask-submit"));
}

const lastRequest = (): AskRequest => (ask.mock.lastCall as Parameters<typeof askCollection>)[2];

beforeEach(() => {
  ask.mockReset();
});
afterEach(cleanup);

describe("AskPanel", () => {
  it("matches the artboard copy and structure", () => {
    renderPanel();
    const panel = screen.getByTestId("ask-panel");
    expect(within(panel).getByRole("heading", { level: 2 }).textContent).toBe(
      "Ask this collection",
    );
    expect(panel.textContent).toContain(
      "Check that your documents answer real questions before attaching them to an assistant.",
    );
    const input = screen.getByLabelText("Test question") as HTMLInputElement;
    expect(input.getAttribute("data-testid")).toBe("ask-question");
    expect(input.placeholder).toBe("How many days of leave do I get when I marry?");
    expect(input.maxLength).toBe(2000);
    expect(screen.getByRole("button", { name: "Ask" })).toBe(screen.getByTestId("ask-submit"));
    const select = screen.getByLabelText("Ask as") as HTMLSelectElement;
    expect(select.value).toBe("authenticated");
    expect(within(select).getByRole("option", { name: "Signed-in user" })).toBeTruthy();
    expect(within(select).getByRole("option", { name: "Anonymous visitor" })).toBeTruthy();
    expect(screen.getByLabelText("Groups")).toBeTruthy();
    expect(panel.textContent).toContain("Comma-separated, e.g. managers, hr");
  });

  it("renders the vi texts with a vi i18n instance", () => {
    renderPanel(makeCollection(), "vi");
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Hỏi thử bộ tài liệu này");
    expect(screen.getByTestId("ask-submit").textContent).toBe("Hỏi");
    expect((screen.getByTestId("ask-question") as HTMLInputElement).placeholder).toBe(
      "Kết hôn được nghỉ mấy ngày?",
    );
    expect(screen.getByLabelText("Hỏi với tư cách")).toBeTruthy();
    expect(screen.getByLabelText("Nhóm")).toBeTruthy();
    expect(screen.getByLabelText("Hỏi với tư cách").textContent).toContain(
      "Người dùng đã đăng nhập",
    );
  });

  it("gives every form field a unique id and a label", () => {
    renderPanel();
    const fields = [
      screen.getByLabelText("Ask as"),
      screen.getByLabelText("Groups"),
      screen.getByLabelText("Test question"),
    ];
    expect(fields.map((field) => field.getAttribute("data-testid"))).toEqual([
      "ask-principal",
      "ask-groups",
      "ask-question",
    ]);
    const ids = fields.map((field) => field.id);
    expect(ids.every((id) => id !== "")).toBe(true);
    expect(new Set(ids).size).toBe(3);
    for (const field of fields) {
      expect(document.querySelector(`label[for="${field.id}"]`)).not.toBeNull();
    }
  });

  it("disables the button while the trimmed question is empty", () => {
    renderPanel();
    const button = screen.getByTestId("ask-submit") as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.change(screen.getByTestId("ask-question"), { target: { value: "   " } });
    expect(button.disabled).toBe(true);
    fireEvent.change(screen.getByTestId("ask-question"), { target: { value: "hi" } });
    expect(button.disabled).toBe(false);
  });

  it("prefills groups for a Restricted collection and hides them for Anonymous", async () => {
    script([]);
    renderPanel(makeCollection({ access_level: "restricted", groups: ["managers"] }));
    expect((screen.getByTestId("ask-groups") as HTMLInputElement).value).toBe("managers");
    submit();
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
    expect(lastRequest()).toEqual({
      question: "How many days?",
      principal: { kind: "authenticated", groups: ["managers"] },
    });
    fireEvent.change(screen.getByTestId("ask-principal"), { target: { value: "anonymous" } });
    expect(screen.queryByTestId("ask-groups")).toBeNull();
    await waitFor(() =>
      expect((screen.getByTestId("ask-submit") as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(screen.getByTestId("ask-submit"));
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(lastRequest().principal).toEqual({ kind: "anonymous", groups: [] });
  });

  it("leaves groups empty for a non-restricted collection", () => {
    renderPanel(makeCollection({ access_level: "public", groups: ["x"] }));
    expect((screen.getByTestId("ask-groups") as HTMLInputElement).value).toBe("");
  });

  it("renders answer with citation spans and passages list", async () => {
    script([
      PASSAGES,
      { type: "delta", text: "You get 3 days [1]." },
      { type: "done", outcome: "answered", answer: "You get 3 days [1].", citations: [1] },
    ]);
    renderPanel();
    submit();
    const answer = await screen.findByTestId("ask-answer");
    await waitFor(() => expect(answer.getAttribute("data-outcome")).toBe("answered"));
    expect(answer.getAttribute("data-language")).toBe("en");
    expect(answer.textContent).toBe("You get 3 days [1].");
    const citations = within(answer).getAllByTestId("ask-citation");
    expect(citations.map((item) => item.textContent)).toEqual(["[1]"]);
    const rows = screen.getAllByTestId("ask-passage");
    expect(rows).toHaveLength(2);
    const [first, second] = rows as [HTMLElement, HTMLElement];
    expect(within(first).getByTestId("ask-passage-source").textContent).toBe(
      "Leave Policy 2026 · §4.1 Personal leave · p. 3",
    );
    expect(within(first).getByTestId("ask-passage-score").textContent).toBe("0.91");
    expect(first.getAttribute("data-number")).toBe("1");
    expect(first.getAttribute("data-cited")).toBe("true");
    expect(first.textContent).toContain("[1]");
    expect(second.getAttribute("data-cited")).toBe("false");
    expect(within(second).getByTestId("ask-passage-source").textContent).toBe("Handbook");
    expect(second.textContent).not.toContain("[2]");
    expect(within(screen.getByTestId("ask-passages")).getByRole("heading").textContent).toBe(
      "Passages found",
    );
  });

  it("renders a row with null section as title and page", async () => {
    script([
      {
        type: "passages",
        language: "en",
        passages: [{ number: 1, title: "Policy", section: null, page: 3, score: 0.3 }],
      },
      { type: "done", outcome: "not_found", answer: "", citations: [] },
    ]);
    renderPanel();
    submit();
    expect((await screen.findByTestId("ask-passage-source")).textContent).toBe("Policy · p. 3");
  });

  it("replaces streamed text on done not_found", async () => {
    script([
      PASSAGES,
      { type: "delta", text: "A guess without citation" },
      { type: "done", outcome: "not_found", answer: "", citations: [] },
    ]);
    renderPanel();
    submit();
    const answer = await screen.findByTestId("ask-answer");
    await waitFor(() => expect(answer.getAttribute("data-outcome")).toBe("not_found"));
    expect(answer.textContent).toBe("I couldn't find this information in the documents.");
    expect(screen.queryByTestId("ask-no-passages")).toBeNull();
    for (const row of screen.getAllByTestId("ask-passage")) {
      expect(row.getAttribute("data-cited")).toBe("false");
    }
  });

  it("not-found text uses the answer language", async () => {
    script([
      { ...PASSAGES, language: "vi" } as AskEvent,
      { type: "done", outcome: "not_found", answer: "", citations: [] },
    ]);
    renderPanel();
    submit();
    const answer = await screen.findByTestId("ask-answer");
    await waitFor(() => expect(answer.getAttribute("data-outcome")).toBe("not_found"));
    expect(answer.getAttribute("data-language")).toBe("vi");
    expect(answer.textContent).toBe("Mình chưa tìm thấy thông tin này trong tài liệu.");
  });

  it("shows only the no-passages message when nothing was found", async () => {
    script([
      { type: "passages", language: "en", passages: [] },
      { type: "done", outcome: "not_found", answer: "", citations: [] },
    ]);
    renderPanel();
    submit();
    const message = await screen.findByTestId("ask-no-passages");
    expect(message.textContent).toBe("No passages found for this question.");
    const answer = screen.getByTestId("ask-answer");
    expect(answer.getAttribute("data-outcome")).toBe("not_found");
    expect(answer.textContent).not.toContain("I couldn't find");
    expect(screen.queryByTestId("ask-passages")).toBeNull();
  });

  it("blocks a second ask while answering", async () => {
    let finish: (result: ApiResult<void>) => void = () => undefined;
    ask.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    renderPanel();
    submit();
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
    const button = screen.getByTestId("ask-submit") as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByTestId("ask-answer").getAttribute("data-outcome")).toBe("answering");
    expect(screen.getByTestId("ask-answer").getAttribute("aria-busy")).toBe("true");
    const input = screen.getByTestId("ask-question");
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.submit(input);
    expect(ask).toHaveBeenCalledTimes(1);
    expect(ask.mock.calls[0]?.[4]?.aborted).toBe(false);
    finish(OK);
    await waitFor(() => expect(button.disabled).toBe(false));
  });

  it("aborts the request on unmount", async () => {
    ask.mockImplementation(() => new Promise(() => undefined));
    const { unmount } = renderPanel();
    submit();
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
    const signal = ask.mock.calls[0]?.[4];
    expect(signal?.aborted).toBe(false);
    unmount();
    expect(signal?.aborted).toBe(true);
  });

  it("removes the partial answer after an error frame and keeps the passages", async () => {
    script([
      PASSAGES,
      { type: "delta", text: "partial" },
      { type: "error", code: "model_unavailable" },
    ]);
    renderPanel();
    submit();
    const alert = await screen.findByTestId("ask-error");
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.textContent).toBe("The model is not available right now. Try again in a moment.");
    expect(screen.queryByTestId("ask-answer")).toBeNull();
    expect(screen.getAllByTestId("ask-passage")).toHaveLength(2);
    expect((screen.getByTestId("ask-submit") as HTMLButtonElement).disabled).toBe(false);
  });

  it("shows the friendly message for 503", async () => {
    script([], { ok: false, status: 503, code: "model_unavailable" });
    renderPanel();
    submit();
    expect((await screen.findByTestId("ask-error")).textContent).toContain("not available");
    expect(screen.queryByTestId("ask-answer")).toBeNull();
  });

  it("shows the friendly message for a body-less 502", async () => {
    script([], { ok: false, status: 502, code: "unknown" });
    renderPanel();
    submit();
    expect((await screen.findByTestId("ask-error")).textContent).toContain("not available");
  });

  it("calls onSessionExpired on 401", async () => {
    script([], { ok: false, status: 401, code: "unauthenticated" });
    const { onSessionExpired } = renderPanel();
    submit();
    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("ask-error")).toBeNull();
  });

  it("calls onNotFound on 404", async () => {
    script([], { ok: false, status: 404, code: "not_found" });
    const { onNotFound } = renderPanel();
    submit();
    await waitFor(() => expect(onNotFound).toHaveBeenCalledTimes(1));
  });

  it("shows the no-permission message on 403", async () => {
    script([], { ok: false, status: 403, code: "forbidden" });
    renderPanel();
    submit();
    expect((await screen.findByTestId("ask-error")).textContent).toBe(
      "You don't have permission to do this.",
    );
  });

  it("shows invalid_group under Groups", async () => {
    script([], { ok: false, status: 422, code: "invalid_group" });
    renderPanel();
    submit();
    const error = await screen.findByTestId("ask-groups-error");
    expect(error.textContent).toBe(
      "Group names must be 1–64 characters, without commas; at most 100 groups.",
    );
    expect(screen.queryByTestId("ask-error")).toBeNull();
  });

  it("states the ask's limit of 100 groups in vi", async () => {
    script([], { ok: false, status: 422, code: "invalid_group" });
    renderPanel(makeCollection(), "vi");
    submit();
    const error = await screen.findByTestId("ask-groups-error");
    expect(error.textContent).toBe(
      "Tên nhóm dài 1–64 ký tự, không chứa dấu phẩy; tối đa 100 nhóm.",
    );
  });

  it("ignores an aborted result", async () => {
    script([], { ok: false, status: 0, code: "aborted" });
    renderPanel();
    submit();
    await waitFor(() => expect(ask).toHaveBeenCalled());
    expect(screen.queryByTestId("ask-error")).toBeNull();
  });
});
