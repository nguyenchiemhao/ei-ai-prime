import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useDialogKeys } from "../components/useDialogKeys";

interface Props {
  mode: "create" | "rename";
  initialName: string;
  sending: boolean;
  /** i18n key of the failure to show, or null. */
  error: string | null;
  onSubmit(name: string): void;
  onClose(): void;
}

const NAME_MAX = 200;

/** Modal to name a new folder or rename one. Escape and Cancel close it. */
export function FolderDialog({ mode, initialName, sending, error, onSubmit, onClose }: Props) {
  const { t } = useTranslation();
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState(initialName);
  const onKeyDown = useDialogKeys(dialogRef, onClose);
  const isCreate = mode === "create";

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (sending) return;
    if (name.trim() === "") {
      inputRef.current?.focus();
      return;
    }
    onSubmit(name.trim());
  }

  return (
    <div className="dialog-backdrop">
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="folder-dialog"
        ref={dialogRef}
        onKeyDown={onKeyDown}
      >
        <h2 className="members-card-title" id={titleId}>
          {t(
            isCreate
              ? "admin.knowledge.folderDialog.createTitle"
              : "admin.knowledge.folderDialog.renameTitle",
          )}
        </h2>
        <form className="dialog-form" noValidate onSubmit={submit}>
          <label className="field">
            <span className="field-label">{t("admin.knowledge.folderDialog.name")}</span>
            <input
              ref={inputRef}
              name="folder-name"
              className="field-input"
              type="text"
              autoComplete="off"
              maxLength={NAME_MAX}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          {error ? (
            <p className="members-alert" role="alert">
              {t(error)}
            </p>
          ) : null}
          <div className="dialog-actions">
            <button type="button" className="button-secondary" onClick={onClose}>
              {t("admin.knowledge.folderDialog.cancel")}
            </button>
            <button type="submit" className="button-primary" disabled={sending}>
              {t(
                isCreate
                  ? "admin.knowledge.folderDialog.create"
                  : "admin.knowledge.folderDialog.save",
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
