import { useState } from "react";
import { useTranslation } from "react-i18next";
import { type FolderItem, createFolder, deleteFolder, renameFolder } from "../api/collections";
import type { ApiResult } from "../api/client";
import { FolderDeleteDialog } from "./FolderDeleteDialog";
import { FolderDialog } from "./FolderDialog";
import { knowledgeErrorKey } from "./errors";

interface Props {
  workspaceId: string;
  collectionId: string;
  folders: readonly FolderItem[];
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

// Orders a flat folder list as a tree: each folder is followed by its subfolders, siblings by name.
// Input: folders (FolderItem[]). Output: FolderItem[]
const orderAsTree = (folders: readonly FolderItem[]): FolderItem[] => {
  const byParent = new Map<string | null, FolderItem[]>();
  for (const item of folders) {
    const siblings = byParent.get(item.parent_id ?? null) ?? [];
    siblings.push(item);
    byParent.set(item.parent_id ?? null, siblings);
  }
  const ordered: FolderItem[] = [];
  const visit = (parentId: string | null) => {
    const siblings = byParent.get(parentId) ?? [];
    siblings.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
    for (const item of siblings) {
      ordered.push(item);
      visit(item.id);
    }
  };
  visit(null);
  return ordered;
};

/** The folders of a collection (nav "Folders"): add, rename and delete, up to 3 levels deep. */
export function FoldersPanel({
  workspaceId,
  collectionId,
  folders,
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
                <span className="folder-name">{item.name}</span>
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
