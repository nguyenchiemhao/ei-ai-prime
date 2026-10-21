import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useDialogKeys } from "../components/useDialogKeys";
import { ASSIGNABLE_ROLES, type AssignableRole, inviteMember, type Member } from "../api/members";

interface Props {
  workspaceId: string;
  onClose(): void;
  onInvited(member: Member): void;
  /** The session ended: the shell sends the user to sign in. */
  onSessionExpired(): void;
}

const NAME_MAX = 200;
const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const DEFAULT_ROLE: AssignableRole = "viewer";

/** The answer is a bare 422 for a bad email or a bad name, so the email shape picks the message. */
function errorKey(status: number, code: string, email: string): string {
  if (status === 422) {
    return EMAIL_SHAPE.test(email.trim())
      ? "admin.members.inviteDialog.invalidInput"
      : "admin.members.inviteDialog.invalidEmail";
  }
  if (status === 409 && code === "already_member")
    return "admin.members.inviteDialog.alreadyMember";
  if (status === 403) return "admin.members.error.forbidden";
  return "admin.members.error.generic";
}

/** Modal "Invite member": email, optional name, role (default Viewer). Escape and Cancel close it. */
export function InviteDialog({ workspaceId, onClose, onInvited, onSessionExpired }: Props) {
  const { t } = useTranslation();
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<AssignableRole>(DEFAULT_ROLE);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    emailRef.current?.focus();
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (sending) return;
    setSending(true);
    setError(null);
    const trimmedName = name.trim();
    const result = await inviteMember(workspaceId, {
      email,
      ...(trimmedName ? { display_name: trimmedName } : {}),
      role,
    });
    setSending(false);
    if (result.ok) onInvited(result.data);
    else if (result.status === 401) onSessionExpired();
    else setError(errorKey(result.status, result.code, email));
  }

  const onKeyDown = useDialogKeys(dialogRef, onClose);

  return (
    <div className="dialog-backdrop">
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={dialogRef}
        onKeyDown={onKeyDown}
      >
        <h2 className="members-card-title" id={titleId}>
          {t("admin.members.inviteDialog.title")}
        </h2>
        <form className="dialog-form" noValidate onSubmit={(event) => void submit(event)}>
          <label className="field">
            <span className="field-label">{t("admin.members.inviteDialog.email")}</span>
            <input
              ref={emailRef}
              className="field-input"
              type="text"
              inputMode="email"
              autoComplete="off"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label className="field">
            <span className="field-label">{t("admin.members.inviteDialog.name")}</span>
            <input
              className="field-input"
              type="text"
              autoComplete="off"
              maxLength={NAME_MAX}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label className="field">
            <span className="field-label">{t("admin.members.inviteDialog.role")}</span>
            <select
              className="field-input"
              value={role}
              onChange={(event) => setRole(event.target.value as AssignableRole)}
            >
              {ASSIGNABLE_ROLES.map((option) => (
                <option key={option} value={option}>
                  {t(`admin.shell.role.${option}`)}
                </option>
              ))}
            </select>
          </label>
          {error ? (
            <p className="members-alert" role="alert">
              {t(error)}
            </p>
          ) : null}
          <div className="dialog-actions">
            <button type="button" className="button-secondary" onClick={onClose}>
              {t("admin.members.inviteDialog.cancel")}
            </button>
            <button type="submit" className="button-primary" disabled={sending}>
              {t("admin.members.inviteDialog.send")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
