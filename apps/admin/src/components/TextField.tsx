import type { ReactNode } from "react";

/** Values of the HTML autocomplete attribute used by the auth forms. */
export const AUTOCOMPLETE = {
  username: "username",
  currentPassword: "current-password",
  newPassword: "new-password",
} as const;

interface TextFieldProps {
  id: string;
  label: string;
  type: "email" | "password";
  autoComplete: (typeof AUTOCOMPLETE)[keyof typeof AUTOCOMPLETE];
  value: string;
  onChange(value: string): void;
  /** Message under the field (also sets aria-invalid). */
  error?: string;
  hint?: string;
  /** Id of an extra element (such as a form-level alert) that describes the field. */
  describedBy?: string;
  /** Content on the label row, right side (the "Forgot password?" link). */
  aside?: ReactNode;
}

/** Label + input + hint + error with the ids wired for assistive technology. */
export function TextField(props: TextFieldProps) {
  const { id, label, type, autoComplete, value, onChange, error, hint, describedBy, aside } = props;
  const errorId = `${id}-error`;
  const hintId = `${id}-hint`;
  const described = [hint ? hintId : null, error ? errorId : null, describedBy ?? null]
    .filter(Boolean)
    .join(" ");
  return (
    <div className="auth-field">
      <div className="auth-field-row">
        <label className="auth-label" htmlFor={id}>
          {label}
        </label>
        {aside}
      </div>
      <input
        id={id}
        className="auth-input"
        type={type}
        autoComplete={autoComplete}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={described || undefined}
      />
      {hint ? (
        <p id={hintId} className="auth-hint">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="auth-field-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
