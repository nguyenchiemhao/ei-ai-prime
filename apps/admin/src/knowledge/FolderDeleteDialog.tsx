import { useEffect, useId, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useDialogKeys } from "../components/useDialogKeys";

interface Props {
  name: string;
  sending: boolean;
  /** i18n key of the failure to show, or null. */
  error: string | null;
  onConfirm(): void;
  onClose(): void;
}

/** Confirmation before a folder is deleted. Cancel and Escape send nothing. */
export function FolderDeleteDialog({ name, sending, error, onConfirm, onClose }: Props) {
  const { t } = useTranslation();
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const onKeyDown = useDialogKeys(dialogRef, onClose);

  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  return (
    <div className="dialog-backdrop">
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="confirm-folder-delete"
        ref={dialogRef}
        onKeyDown={onKeyDown}
      >
        <h2 className="members-card-title" id={titleId}>
          {t("admin.knowledge.folderDelete.title")}
        </h2>
        <p className="dialog-text">{t("admin.knowledge.folderDelete.text", { name })}</p>
        {error ? (
          <p className="members-alert" role="alert">
            {t(error)}
          </p>
        ) : null}
        <div className="dialog-actions">
          <button ref={cancelRef} type="button" className="button-secondary" onClick={onClose}>
            {t("admin.knowledge.folderDelete.cancel")}
          </button>
          <button type="button" className="button-danger" disabled={sending} onClick={onConfirm}>
            {t("admin.knowledge.folderDelete.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}
