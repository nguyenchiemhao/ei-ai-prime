import { useEffect, useId, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useDialogKeys } from "../components/useDialogKeys";

interface Props {
  onConfirm(): void;
  onCancel(): void;
}

/** Confirmation shown before a collection becomes Public. Cancel and Escape send nothing. */
export function ConfirmPublicDialog({ onConfirm, onCancel }: Props) {
  const { t } = useTranslation();
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const onKeyDown = useDialogKeys(dialogRef, onCancel);

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
        data-testid="confirm-public-dialog"
        ref={dialogRef}
        onKeyDown={onKeyDown}
      >
        <h2 className="members-card-title" id={titleId}>
          {t("admin.knowledge.confirmPublic.title")}
        </h2>
        <p className="dialog-text">{t("admin.knowledge.confirmPublic.text")}</p>
        <div className="dialog-actions">
          <button ref={cancelRef} type="button" className="button-secondary" onClick={onCancel}>
            {t("admin.knowledge.confirmPublic.cancel")}
          </button>
          <button type="button" className="button-primary" onClick={onConfirm}>
            {t("admin.knowledge.confirmPublic.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}
