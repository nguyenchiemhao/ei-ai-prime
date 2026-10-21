import { type FormEvent, useEffect, useId, useRef, useState } from "react";
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

/** Danger confirmation: the user types the collection name; the button enables on an exact match. */
export function DeleteCollectionDialog({ name, sending, error, onConfirm, onClose }: Props) {
  const { t } = useTranslation();
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [typed, setTyped] = useState("");
  const onKeyDown = useDialogKeys(dialogRef, onClose);
  const matches = typed.trim() === name;

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (matches && !sending) onConfirm();
  }

  return (
    <div className="dialog-backdrop">
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="delete-collection-dialog"
        ref={dialogRef}
        onKeyDown={onKeyDown}
      >
        <h2 className="members-card-title" id={titleId}>
          {t("admin.knowledge.deleteCollection.title", { name })}
        </h2>
        <p className="dialog-text">{t("admin.knowledge.deleteCollection.consequence")}</p>
        <form className="dialog-form" noValidate onSubmit={submit}>
          <label className="field">
            <span className="field-label">
              {t("admin.knowledge.deleteCollection.input", { name })}
            </span>
            <input
              ref={inputRef}
              name="confirm-name"
              className="field-input"
              type="text"
              autoComplete="off"
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
            />
          </label>
          {error ? (
            <p className="members-alert" role="alert">
              {t(error)}
            </p>
          ) : null}
          <div className="dialog-actions">
            <button type="button" className="button-secondary" onClick={onClose}>
              {t("admin.knowledge.deleteCollection.cancel")}
            </button>
            <button
              type="submit"
              className="button-danger"
              data-testid="confirm-delete-collection"
              disabled={!matches || sending}
            >
              {t("admin.knowledge.deleteCollection.confirm")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
