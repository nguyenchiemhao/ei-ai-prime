import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { type DocumentItem, deleteDocument } from "../api/documents";
import { useDialogKeys } from "../components/useDialogKeys";

interface Props {
  workspaceId: string;
  collectionId: string;
  document: DocumentItem;
  /** The document is gone (removed now, or already missing). */
  onRemoved(document: DocumentItem): void;
  onClose(): void;
  /** The session ended: the shell sends the user to sign in. */
  onSessionExpired(): void;
}

const UNAUTHENTICATED = 401;
const FORBIDDEN = 403;
const NOT_FOUND = 404;

/** Confirmation to remove a document; nothing is sent until the user confirms. */
export function RemoveDocumentDialog({
  workspaceId,
  collectionId,
  document,
  onRemoved,
  onClose,
  onSessionExpired,
}: Props) {
  const { t } = useTranslation();
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const onKeyDown = useDialogKeys(dialogRef, onClose);

  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  // Deletes the document and reports the outcome to the page.
  async function confirm() {
    if (sending) return;
    setSending(true);
    setError(null);
    const result = await deleteDocument(workspaceId, collectionId, document.id);
    setSending(false);
    if (result.ok || result.status === NOT_FOUND) onRemoved(document);
    else if (result.status === UNAUTHENTICATED) onSessionExpired();
    else {
      setError(
        result.status === FORBIDDEN
          ? "admin.knowledge.error.forbidden"
          : "admin.knowledge.error.generic",
      );
    }
  }

  return (
    <div className="dialog-backdrop">
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="remove-document-dialog"
        ref={dialogRef}
        onKeyDown={onKeyDown}
      >
        <h2 className="members-card-title" id={titleId}>
          {t("admin.knowledge.documents.removeDialog.title", { name: document.name })}
        </h2>
        <p className="dialog-text">{t("admin.knowledge.documents.removeDialog.text")}</p>
        {error ? (
          <p className="members-alert" role="alert">
            {t(error)}
          </p>
        ) : null}
        <div className="dialog-actions">
          <button type="button" className="button-secondary" ref={cancelRef} onClick={onClose}>
            {t("admin.knowledge.documents.removeDialog.cancel")}
          </button>
          <button
            type="button"
            className="button-danger"
            data-testid="confirm-remove-document"
            disabled={sending}
            onClick={() => void confirm()}
          >
            {t("admin.knowledge.documents.removeDialog.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}
