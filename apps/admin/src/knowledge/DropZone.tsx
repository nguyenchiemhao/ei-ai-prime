import { type DragEvent, type RefObject, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { FolderItem } from "../api/collections";
import { uploadDocument } from "../api/documents";
import { uploadRejectionKey } from "./errors";
import { SUPPORTED_EXTENSIONS, checkFile } from "./uploadRules";

interface Props {
  workspaceId: string;
  collectionId: string;
  /** The selected folder; null while "All documents" is selected. */
  folder: FolderItem | null;
  /** The picker the header's "Upload files" button opens. */
  inputRef: RefObject<HTMLInputElement | null>;
  /** A batch finished: the folder counts and the document list are stale. */
  onUploaded(): void;
  /** The session ended: the shell sends the user to sign in. */
  onSessionExpired(): void;
}

interface Pending {
  id: number;
  name: string;
}

/** One "was not uploaded" line and the file it is about. */
interface Rejection {
  name: string;
  line: string;
}

const MAX_PARALLEL_UPLOADS = 3;
const UNAUTHENTICATED = 401;
const ACCEPT = SUPPORTED_EXTENSIONS.join(",");

/** Drop zone and file picker that upload files into the selected folder, at most 3 at a time. */
export function DropZone({
  workspaceId,
  collectionId,
  folder,
  inputRef,
  onUploaded,
  onSessionExpired,
}: Props) {
  const { t } = useTranslation();
  const [pending, setPending] = useState<Pending[]>([]);
  const [rejections, setRejections] = useState<Rejection[]>([]);
  const [dragging, setDragging] = useState(false);
  const nextId = useRef(0);

  // Builds the rejection line of one file; an unknown code gets the generic text.
  function rejection(name: string, code: string): Rejection {
    return { name, line: t(uploadRejectionKey(code), { name }) };
  }

  // Drops the earlier lines of these files: a new upload of a file replaces its old outcome.
  function withoutLinesOf(current: Rejection[], names: Set<string>): Rejection[] {
    return current.filter((item) => !names.has(item.name));
  }

  // Uploads one accepted file; a failure becomes a rejection line, a 401 ends the session.
  async function uploadOne(target: FolderItem, file: File, id: number) {
    const result = await uploadDocument(workspaceId, collectionId, target.id, file);
    setPending((current) => current.filter((item) => item.id !== id));
    if (result.ok) {
      setRejections((current) => withoutLinesOf(current, new Set([file.name])));
      return;
    }
    if (result.status === UNAUTHENTICATED) onSessionExpired();
    else setRejections((current) => [...current, rejection(file.name, result.code)]);
  }

  // Checks the files, rejects the bad ones at once and uploads the rest through a small worker pool.
  async function handleFiles(files: File[]) {
    if (!folder || files.length === 0) return;
    const accepted: { file: File; id: number }[] = [];
    const refused: Rejection[] = [];

    files.forEach((file) => {
      const code = checkFile(file);
      if (code) refused.push(rejection(file.name, code));
      else accepted.push({ file, id: nextId.current++ });
    });
    const names = new Set(files.map((file) => file.name));
    setRejections((current) => [...withoutLinesOf(current, names), ...refused]);
    setPending((current) => [
      ...current,
      ...accepted.map(({ file, id }) => ({ id, name: file.name })),
    ]);
    const queue = [...accepted];
    const worker = async () => {
      for (let next = queue.shift(); next; next = queue.shift()) {
        await uploadOne(folder, next.file, next.id);
      }
    };
    await Promise.all(Array.from({ length: Math.min(MAX_PARALLEL_UPLOADS, queue.length) }, worker));
    if (accepted.length > 0) onUploaded();
  }

  function onDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setDragging(false);
    void handleFiles(Array.from(event.dataTransfer.files));
  }

  return (
    <section
      className="drop-zone"
      data-testid="drop-zone"
      data-dragging={dragging}
      onDragOver={(event) => {
        event.preventDefault();
        if (folder) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      {folder ? (
        <>
          <div className="drop-zone-text">
            <h2 className="drop-zone-title">
              {t("admin.knowledge.documents.dropTitle", { name: folder.name })}
            </h2>
            <p className="drop-zone-hint">{t("admin.knowledge.documents.dropHint")}</p>
          </div>
          <button
            type="button"
            className="button-secondary"
            data-testid="browse-files"
            onClick={() => inputRef.current?.click()}
          >
            {t("admin.knowledge.documents.browse")}
          </button>
          <input
            ref={inputRef}
            type="file"
            hidden
            id="knowledge-file-input"
            name="files"
            multiple
            accept={ACCEPT}
            aria-label={t("admin.knowledge.documents.browseLabel")}
            data-testid="file-input"
            onChange={(event) => {
              const chosen = Array.from(event.target.files ?? []);
              event.target.value = "";
              void handleFiles(chosen);
            }}
          />
        </>
      ) : (
        <p className="drop-zone-hint">{t("admin.knowledge.documents.chooseFolder")}</p>
      )}
      {pending.length > 0 ? (
        <ul className="upload-list">
          {pending.map((item) => (
            <li key={item.id} data-testid="upload-pending">
              <span>{item.name}</span> <span>{t("admin.knowledge.documents.uploading")}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {rejections.length > 0 ? (
        <div className="knowledge-alert upload-rejections" role="alert">
          {rejections.map((item, index) => (
            <p key={index} data-testid="upload-rejection">
              {item.line}
            </p>
          ))}
        </div>
      ) : null}
    </section>
  );
}
