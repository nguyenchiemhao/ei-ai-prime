import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createRef } from "react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FolderItem } from "../api/collections";
import { clearCsrfToken } from "../api/client";
import { createI18n } from "../i18n";
import { callsTo, json, mockApi } from "../test/renderApp";
import { DropZone } from "./DropZone";

const UPLOAD = "POST /workspaces/w1/collections/c1/folders/f1/documents";
const FOLDER: FolderItem = {
  id: "f1",
  name: "Policies",
  depth: 1,
  parent_id: null,
  document_count: 0,
};

beforeEach(() => clearCsrfToken());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const fileOf = (name: string, size = 3): File => {
  const file = new File(["abc"], name);
  Object.defineProperty(file, "size", { value: size });
  return file;
};

function setup(folder: FolderItem | null = FOLDER) {
  const onUploaded = vi.fn();
  const onSessionExpired = vi.fn();
  render(
    <I18nextProvider i18n={createI18n()}>
      <DropZone
        workspaceId="w1"
        collectionId="c1"
        folder={folder}
        inputRef={createRef<HTMLInputElement>()}
        onUploaded={onUploaded}
        onSessionExpired={onSessionExpired}
      />
    </I18nextProvider>,
  );
  return { onUploaded, onSessionExpired };
}

const choose = (...files: File[]) =>
  fireEvent.change(screen.getByLabelText("Browse files"), { target: { files } });

describe("DropZone", () => {
  it("rejects_exe_and_doc_before_upload_with_supported_list", () => {
    const api = mockApi({});
    setup();
    choose(fileOf("setup.exe"), fileOf("old.doc"));
    const lines = screen.getAllByTestId("upload-rejection").map((line) => line.textContent);
    expect(lines).toEqual([
      "setup.exe was not uploaded: this format is not supported. Supported formats: PDF with text, DOCX, MD, TXT.",
      "old.doc was not uploaded: this format is not supported. Supported formats: PDF with text, DOCX, MD, TXT.",
    ]);
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(api).not.toHaveBeenCalled();
  });

  it("rejects_file_over_50_mb_before_upload", () => {
    const api = mockApi({});
    setup();
    choose(fileOf("big.pdf", 52_428_801));
    expect(screen.getByTestId("upload-rejection").textContent).toBe(
      "big.pdf was not uploaded: files can be up to 50 MB.",
    );
    expect(api).not.toHaveBeenCalled();
  });

  it("uploads_accepted_files_with_header_and_csrf", async () => {
    const api = mockApi({ [UPLOAD]: () => json(201, { id: "d1" }) });
    const { onUploaded } = setup();
    const file = fileOf("Policy ñ.PDF");
    choose(fileOf("setup.exe"), file);
    expect(screen.getByTestId("upload-pending").textContent).toContain("Uploading…");
    await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(1));
    const [call] = callsTo(api, UPLOAD);
    const headers = call?.headers as Record<string, string>;
    expect(headers["X-File-Name"]).toBe(encodeURIComponent("Policy ñ.PDF"));
    expect(headers["Content-Type"]).toBe("application/octet-stream");
    expect(headers["X-CSRF-Token"]).toBe("t");
    expect(call?.body).toBe(file);
    expect(callsTo(api, UPLOAD)).toHaveLength(1);
    expect(screen.queryByTestId("upload-pending")).toBeNull();
    expect(screen.getAllByTestId("upload-rejection")).toHaveLength(1);
  });

  it("shows_choose_a_folder_when_all_documents_selected", () => {
    setup(null);
    expect(screen.getByTestId("drop-zone").textContent).toBe("Choose a folder to upload files.");
    expect(screen.queryByTestId("browse-files")).toBeNull();
    expect(screen.queryByTestId("file-input")).toBeNull();
  });

  it("gives_the_hidden_file_input_a_name_and_id", () => {
    setup();
    const input = screen.getByTestId("file-input");
    expect(input.getAttribute("name")).toBe("files");
    expect(input.getAttribute("id")).toBe("knowledge-file-input");
  });

  it("maps_server_codes_to_messages", async () => {
    const codes = [
      "file_too_large",
      "empty_file",
      "storage_quota_exceeded",
      "invalid_file_name",
      "boom",
    ];
    const answers = [...codes];
    mockApi({ [UPLOAD]: () => json(422, { detail: answers.shift() }) });
    const { onUploaded } = setup();
    choose(...codes.map((_, index) => fileOf(`f${index}.txt`)));
    await waitFor(() => expect(onUploaded).toHaveBeenCalled());
    const lines = screen.getAllByTestId("upload-rejection").map((line) => line.textContent);
    expect([...lines].sort()).toEqual(
      [
        "f0.txt was not uploaded: files can be up to 50 MB.",
        "f1.txt was not uploaded: the file is empty.",
        "f2.txt was not uploaded: your organization's storage is full (1 GB).",
        "f3.txt was not uploaded: the file name is not valid.",
        "f4.txt was not uploaded. Try again.",
      ].sort(),
    );
  });

  it("uploads_at_most_three_at_a_time", async () => {
    let running = 0;
    let peak = 0;
    const releases: (() => void)[] = [];
    mockApi({
      [UPLOAD]: () => {
        running += 1;
        peak = Math.max(peak, running);
        return new Promise<Response>((resolve) =>
          releases.push(() => {
            running -= 1;
            resolve(json(201, { id: "d" }));
          }),
        ) as unknown as Response;
      },
    });
    const { onUploaded } = setup();
    choose(...[1, 2, 3, 4, 5].map((n) => fileOf(`f${n}.txt`)));
    expect(screen.getAllByTestId("upload-pending")).toHaveLength(5);
    await waitFor(() => expect(releases).toHaveLength(3));
    releases.splice(0).forEach((release) => release());
    await waitFor(() => expect(releases).toHaveLength(2));
    releases.splice(0).forEach((release) => release());
    await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(1));
    expect(peak).toBe(3);
  });

  it("uploads_dropped_files", async () => {
    mockApi({ [UPLOAD]: () => json(201, { id: "d1" }) });
    const { onUploaded } = setup();
    fireEvent.drop(screen.getByTestId("drop-zone"), {
      dataTransfer: { files: [fileOf("a.md")] },
    });
    await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(1));
    expect(within(screen.getByTestId("drop-zone")).queryByRole("alert")).toBeNull();
  });

  it("an_expired_session_is_reported_instead_of_a_rejection", async () => {
    mockApi({ [UPLOAD]: () => json(401, { detail: "unauthenticated" }) });
    const { onSessionExpired } = setup();
    choose(fileOf("a.txt"));
    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("upload-rejection")).toBeNull();
  });

  it("a_second_drop_keeps_the_first_batch_lines", async () => {
    const releases: (() => void)[] = [];
    mockApi({
      [UPLOAD]: () =>
        new Promise<Response>((resolve) =>
          releases.push(() => resolve(json(201, { id: "d" }))),
        ) as unknown as Response,
    });
    setup();
    choose(fileOf("first.txt"), fileOf("first.exe"));
    await waitFor(() => expect(releases).toHaveLength(1));
    choose(fileOf("second.md"), fileOf("second.doc"));
    const pending = () => screen.getAllByTestId("upload-pending").map((li) => li.textContent);
    expect(pending()).toHaveLength(2);
    expect(pending()[0]).toContain("first.txt");
    expect(pending()[1]).toContain("second.md");
    const lines = screen.getAllByTestId("upload-rejection").map((line) => line.textContent);
    expect(lines[0]).toContain("first.exe");
    expect(lines[1]).toContain("second.doc");
    releases.splice(0).forEach((release) => release());
    await waitFor(() => expect(releases).toHaveLength(1));
    await waitFor(() => expect(screen.getAllByTestId("upload-pending")).toHaveLength(1));
    expect(screen.getAllByTestId("upload-pending")[0]?.textContent).toContain("second.md");
    releases.splice(0).forEach((release) => release());
    await waitFor(() => expect(screen.queryByTestId("upload-pending")).toBeNull());
  });

  it("a_new_upload_of_a_file_clears_its_old_rejection_line", async () => {
    const answers = [json(403, { detail: "forbidden" }), json(201, { id: "d" })];
    const releases: (() => void)[] = [];
    mockApi({
      [UPLOAD]: () =>
        new Promise<Response>((resolve) => {
          const answer = answers.shift() as Response;
          releases.push(() => resolve(answer));
        }) as unknown as Response,
    });
    setup();
    choose(fileOf("a.txt"), fileOf("b.exe"));
    await waitFor(() => expect(releases).toHaveLength(1));
    releases.splice(0).forEach((release) => release());
    await waitFor(() => expect(screen.getAllByTestId("upload-rejection")).toHaveLength(2));

    choose(fileOf("a.txt"));
    const lines = () => screen.getAllByTestId("upload-rejection").map((line) => line.textContent);
    expect(lines()).toHaveLength(1);
    expect(lines()[0]).toContain("b.exe");
    await waitFor(() => expect(releases).toHaveLength(1));
    releases.splice(0).forEach((release) => release());
    await waitFor(() => expect(screen.queryByTestId("upload-pending")).toBeNull());
    expect(lines()).toEqual([expect.stringContaining("b.exe")]);
  });

  it("lays_out_heading_and_hint_left_of_browse_as_one_banner", () => {
    mockApi({});
    setup();
    const zone = screen.getByTestId("drop-zone");
    const text = zone.querySelector(".drop-zone-text") as HTMLElement;
    expect(within(text).getByRole("heading").textContent).toBe("Drop files into Policies");
    expect(text.nextElementSibling).toBe(screen.getByTestId("browse-files"));
  });
});
