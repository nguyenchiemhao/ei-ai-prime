import { type RefObject, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { FolderItem } from "../api/collections";
import type { DocumentItem } from "../api/documents";
import { DocumentsTable } from "./DocumentsTable";
import { DropZone } from "./DropZone";
import { PreviewTextDialog } from "./PreviewTextDialog";
import { RemoveDocumentDialog } from "./RemoveDocumentDialog";
import { useDocuments } from "./useDocuments";

interface Props {
  workspaceId: string;
  collectionId: string;
  /** The selected folder; null while "All documents" is selected. */
  folder: FolderItem | null;
  inputRef: RefObject<HTMLInputElement | null>;
  /** Documents were added or removed: the folder counts are stale. */
  onChanged(): void;
  /** A document was removed (the page shows the confirmation message). */
  onRemoved(name: string): void;
  onSessionExpired(): void;
}

const UNAUTHENTICATED = 401;

/** Right column of the collection page: the drop zone, the document table and its dialogs. */
export function DocumentsPanel({
  workspaceId,
  collectionId,
  folder,
  inputRef,
  onChanged,
  onRemoved,
  onSessionExpired,
}: Props) {
  const { t, i18n } = useTranslation();
  const { documents, reload, error, loading } = useDocuments(
    workspaceId,
    collectionId,
    folder?.id ?? null,
    onChanged,
  );
  const [previewing, setPreviewing] = useState<DocumentItem | null>(null);
  const [removing, setRemoving] = useState<DocumentItem | null>(null);
  const sessionEnded = error?.status === UNAUTHENTICATED;

  useEffect(() => {
    if (sessionEnded) onSessionExpired();
  }, [sessionEnded, onSessionExpired]);

  // Closes the dialog, reloads the list and the folder counts, and reports the removal.
  function afterRemoved(document: DocumentItem) {
    setRemoving(null);
    reload();
    onChanged();
    onRemoved(document.name);
  }

  return (
    <>
      <DropZone
        workspaceId={workspaceId}
        collectionId={collectionId}
        folder={folder}
        inputRef={inputRef}
        onUploaded={() => {
          reload();
          onChanged();
        }}
        onSessionExpired={onSessionExpired}
      />
      <section className="members-card">
        <h2 className="members-card-title">{t("admin.knowledge.detail.documentsTitle")}</h2>
        {error && !sessionEnded ? (
          <p className="knowledge-alert" role="alert">
            {t("admin.knowledge.error.generic")}
          </p>
        ) : null}
        {loading || (error && documents.length === 0) ? null : (
          <DocumentsTable
            documents={documents}
            locale={i18n.language}
            inFolder={folder !== null}
            onPreview={setPreviewing}
            onRemove={setRemoving}
          />
        )}
      </section>
      {previewing ? (
        <PreviewTextDialog
          workspaceId={workspaceId}
          collectionId={collectionId}
          document={previewing}
          onClose={() => setPreviewing(null)}
          onSessionExpired={onSessionExpired}
        />
      ) : null}
      {removing ? (
        <RemoveDocumentDialog
          workspaceId={workspaceId}
          collectionId={collectionId}
          document={removing}
          onRemoved={afterRemoved}
          onClose={() => setRemoving(null)}
          onSessionExpired={onSessionExpired}
        />
      ) : null}
    </>
  );
}
