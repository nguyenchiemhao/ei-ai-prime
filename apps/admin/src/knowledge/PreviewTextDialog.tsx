import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { type DocumentItem, type DocumentText, getDocumentText } from "../api/documents";
import { useDialogKeys } from "../components/useDialogKeys";

interface Props {
  workspaceId: string;
  collectionId: string;
  document: DocumentItem;
  onClose(): void;
  /** The session ended: the shell sends the user to sign in. */
  onSessionExpired(): void;
}

const UNAUTHENTICATED = 401;

/** Read-only dialog with the extracted text of a ready document (first 100 000 characters). */
export function PreviewTextDialog({
  workspaceId,
  collectionId,
  document,
  onClose,
  onSessionExpired,
}: Props) {
  const { t } = useTranslation();
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [text, setText] = useState<DocumentText | null>(null);
  const [failed, setFailed] = useState(false);
  const sessionExpiredRef = useRef(onSessionExpired);
  const onKeyDown = useDialogKeys(dialogRef, onClose);

  useEffect(() => {
    sessionExpiredRef.current = onSessionExpired;
  });

  useEffect(() => {
    let cancelled = false;
    void getDocumentText(workspaceId, collectionId, document.id).then((result) => {
      if (cancelled) return;
      if (result.ok) setText(result.data);
      else if (result.status === UNAUTHENTICATED) sessionExpiredRef.current();
      else setFailed(true);
    });
    return () => {
      cancelled = true;
    };
  }, [workspaceId, collectionId, document.id]);

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  return (
    <div className="dialog-backdrop">
      <div
        className="dialog dialog-wide"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="preview-text-dialog"
        ref={dialogRef}
        onKeyDown={onKeyDown}
      >
        <h2 className="members-card-title" id={titleId}>
          {document.name}
        </h2>
        {text ? (
          <pre className="preview-text" data-testid="preview-text-content" tabIndex={0}>
            {text.text}
          </pre>
        ) : null}
        {text?.truncated ? (
          <p className="dialog-text" data-testid="preview-truncated">
            {t("admin.knowledge.documents.preview.truncated")}
          </p>
        ) : null}
        {!text && !failed ? (
          <p className="dialog-text">{t("admin.knowledge.documents.preview.loading")}</p>
        ) : null}
        {failed ? (
          <p className="members-alert" role="alert">
            {t("admin.knowledge.documents.preview.error")}
          </p>
        ) : null}
        <div className="dialog-actions">
          <button type="button" className="button-secondary" ref={closeRef} onClick={onClose}>
            {t("admin.knowledge.documents.preview.close")}
          </button>
        </div>
      </div>
    </div>
  );
}
