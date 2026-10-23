import { useState } from "react";
import { useTranslation } from "react-i18next";
import { type FolderItem, createFolder, deleteFolder, renameFolder } from "../api/collections";
import type { ApiResult } from "../api/client";
import { FolderDeleteDialog } from "./FolderDeleteDialog";
import { FolderDialog } from "./FolderDialog";
import { knowledgeErrorKey } from "./errors";
import { orderAsTree } from "./folderTree";

interface Props {
  workspaceId: string;
  collectionId: string;
  folders: readonly FolderItem[];
  /** The selected folder id, or ALL_DOCUMENTS. */
  selectedId: string;
  onSelect(id: string): void;
  onChange(folders: FolderItem[]): void;
  /** The session ended: the shell sends the user to sign in. */
  onSessionExpired(): void;
  /** A request answered 404: the folder or the whole collection is gone. */
  onNotFound(): void;
}

type Dialog =
  | { kind: "create"; parent: FolderItem | null }
  | { kind: "rename"; folder: FolderItem }
  | { kind: "delete"; folder: FolderItem };

const UNAUTHENTICATED = 401;
const NOT_FOUND = 404;
const MAX_DEPTH = 3;

/** The selection value of the "All documents" entry. */
export const ALL_DOCUMENTS = "all";

/** The folders of a collection (nav "Folders"): select, add, rename and delete, up to 3 levels deep. */
export function FoldersPanel({
  workspaceId,
  collectionId,
  folders,
  selectedId,
  onSelect,
  onChange,
  onSessionExpired,
  onNotFound,
}: Props) {
  const { t } = useTranslation();
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Opens a dialog with a clean state.
  function open(next: Dialog) {
    setError(null);
    setDialog(next);
  }

  // Runs one folder request; on success applies the change and closes, otherwise shows the error.
  async function run<T>(request: Promise<ApiResult<T>>, apply: (data: T) => FolderItem[]) {
    setSending(true);
    setError(null);
    const result = await request;
    setSending(false);
    if (result.ok) {
      onChange(apply(result.data));
      setDialog(null);
    } else if (result.status === UNAUTHENTICATED) {
      setDialog(null);
      onSessionExpired();
    } else {
      if (result.status === NOT_FOUND) onNotFound();
      setError(knowledgeErrorKey(result.status, result.code, "folder"));
    }
  }

  function submitName(name: string) {
    if (dialog?.kind === "create") {
      const parentId = dialog.parent?.id ?? null;
      void run(createFolder(workspaceId, collectionId, { name, parent_id: parentId }), (added) => [
        ...folders,
        added,
      ]);
    } else if (dialog?.kind === "rename") {
      const { id } = dialog.folder;
      void run(renameFolder(workspaceId, collectionId, id, { name }), (renamed) =>
        folders.map((item) => (item.id === id ? renamed : item)),
      );
    }
  }

  function confirmDelete() {
    if (dialog?.kind !== "delete") return;
    const { id } = dialog.folder;
    void run(deleteFolder(workspaceId, collectionId, id), () =>
      folders.filter((item) => item.id !== id),
    );
  }

  const totalCount = folders.reduce((sum, item) => sum + item.document_count, 0);

  return (
    <>
      <nav
        className="folders-panel members-card"
        aria-label={t("admin.knowledge.detail.foldersLabel")}
        data-testid="folders-panel"
      >
        <div className="folders-head">
          <h2 className="members-card-title">{t("admin.knowledge.detail.foldersLabel")}</h2>
          <button
            type="button"
            className="button-secondary"
            data-testid="new-folder"
            onClick={() => open({ kind: "create", parent: null })}
          >
            {t("admin.knowledge.detail.newFolder")}
          </button>
        </div>
        <button
          type="button"
          className="folder-select all-documents"
          data-testid="all-documents"
          aria-current={selectedId === ALL_DOCUMENTS ? "true" : undefined}
          onClick={() => onSelect(ALL_DOCUMENTS)}
        >
          <span className="folder-name">{t("admin.knowledge.documents.allDocuments")}</span>
          <span className="folder-count" data-testid="folder-count">
            {totalCount}
          </span>
        </button>
        {folders.length === 0 ? (
          <p className="folders-empty">{t("admin.knowledge.detail.noFolders")}</p>
        ) : (
          <ul className="folders-list">
            {orderAsTree(folders).map((item) => (
              <li
                key={item.id}
                className="folder-row"
                data-testid="folder-row"
                data-folder-id={item.id}
                data-depth={item.depth}
              >
                <button
                  type="button"
                  className="folder-select"
                  data-testid="folder-select"
                  aria-current={selectedId === item.id ? "true" : undefined}
                  onClick={() => onSelect(item.id)}
                >
                  <span className="folder-name">{item.name}</span>
                  <span className="folder-count" data-testid="folder-count">
                    {item.document_count}
                  </span>
                </button>
                <span className="folder-actions">
                  {item.depth < MAX_DEPTH ? (
                    <button
                      type="button"
                      className="button-link"
                      onClick={() => open({ kind: "create", parent: item })}
                    >
                      {t("admin.knowledge.detail.addSubfolder", { name: item.name })}
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="button-link"
                    onClick={() => open({ kind: "rename", folder: item })}
                  >
                    {t("admin.knowledge.detail.rename", { name: item.name })}
                  </button>
                  <button
                    type="button"
                    className="button-link"
                    onClick={() => open({ kind: "delete", folder: item })}
                  >
                    {t("admin.knowledge.detail.delete", { name: item.name })}
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </nav>
      {dialog?.kind === "create" || dialog?.kind === "rename" ? (
        <FolderDialog
          mode={dialog.kind}
          initialName={dialog.kind === "rename" ? dialog.folder.name : ""}
          sending={sending}
          error={error}
          onSubmit={submitName}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {dialog?.kind === "delete" ? (
        <FolderDeleteDialog
          name={dialog.folder.name}
          sending={sending}
          error={error}
          onConfirm={confirmDelete}
          onClose={() => setDialog(null)}
        />
      ) : null}
    </>
  );
}
