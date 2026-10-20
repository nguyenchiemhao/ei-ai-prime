import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router";
import { setPassword as setPasswordRequest } from "../api/auth";
import { AuthLayout } from "../components/AuthLayout";
import { AUTOCOMPLETE, TextField } from "../components/TextField";
import { usePageTitle } from "../components/usePageTitle";
import { PATHS } from "../paths";

const ERROR_ID = "set-password-error";
const MIN_LENGTH = 12;
const MAX_LENGTH = 128;

/** One-time token from the address fragment (`#token=...`), or "" when absent. */
function readToken(): string {
  return new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "";
}

/** The token must not stay in the address bar, history or referrers. */
function dropFragment() {
  if (window.location.hash) {
    window.history.replaceState(
      window.history.state,
      "",
      window.location.pathname + window.location.search,
    );
  }
}

/** `/set-password` (new user) and `/reset` (forgot password) share this page. */
export function SetPasswordPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const isReset = useLocation().pathname === PATHS.reset;
  const [token, setToken] = useState(readToken);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [passwordError, setPasswordError] = useState<string | undefined>();
  const [confirmError, setConfirmError] = useState<string | undefined>();
  const [error, setError] = useState<string | undefined>(
    token ? undefined : t("admin.setPassword.invalidLink"),
  );
  const [submitting, setSubmitting] = useState(false);
  const title = t(isReset ? "admin.setPassword.titleReset" : "admin.setPassword.titleSet");
  usePageTitle(title);

  useEffect(() => {
    dropFragment();
    // Another link opened in this tab changes only the fragment, so the page is not reloaded:
    // take its token and start over with an empty form.
    function onHashChange() {
      if (!window.location.hash) return;
      const next = readToken();
      setToken(next);
      setPassword("");
      setConfirm("");
      setPasswordError(undefined);
      setConfirmError(undefined);
      setError(next ? undefined : t("admin.setPassword.invalidLink"));
      dropFragment();
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [t]);

  function lengthError(value: string): string | undefined {
    if (value.length < MIN_LENGTH) return t("admin.setPassword.tooShort");
    if (value.length > MAX_LENGTH) return t("admin.setPassword.tooLong");
    return undefined;
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    const nextPasswordError = lengthError(password);
    const nextConfirmError =
      !nextPasswordError && confirm !== password ? t("admin.setPassword.mismatch") : undefined;
    setPasswordError(nextPasswordError);
    setConfirmError(nextConfirmError);
    if (nextPasswordError || nextConfirmError) return;
    if (!token) {
      setError(t("admin.setPassword.invalidLink"));
      return;
    }

    setError(undefined);
    setSubmitting(true);
    const result = await setPasswordRequest(token, password);
    if (result.ok) {
      navigate(PATHS.signIn, { replace: true, state: { notice: "passwordSet" } });
      return;
    }
    if (result.status === 400) setError(t("admin.setPassword.invalidLink"));
    else if (result.status === 422) {
      setPasswordError(
        t(
          result.code === "password_too_long"
            ? "admin.setPassword.tooLong"
            : "admin.setPassword.tooShort",
        ),
      );
    } else setError(t("admin.signIn.unavailable"));
    setSubmitting(false);
  }

  return (
    <AuthLayout>
      <form className="auth-card" noValidate onSubmit={(event) => void onSubmit(event)}>
        <div className="auth-head">
          <h1 className="auth-title">{title}</h1>
        </div>
        <TextField
          id="set-password-new"
          label={t("admin.setPassword.newPassword")}
          type="password"
          autoComplete={AUTOCOMPLETE.newPassword}
          value={password}
          onChange={setPassword}
          hint={t("admin.setPassword.hint")}
          error={passwordError}
        />
        <TextField
          id="set-password-confirm"
          label={t("admin.setPassword.confirm")}
          type="password"
          autoComplete={AUTOCOMPLETE.newPassword}
          value={confirm}
          onChange={setConfirm}
          error={confirmError}
          describedBy={error ? ERROR_ID : undefined}
        />
        {error ? (
          <p id={ERROR_ID} className="auth-alert" role="alert" data-testid="set-password-error">
            {error}
          </p>
        ) : null}
        <button className="auth-button" type="submit" disabled={submitting}>
          {t("admin.setPassword.submit")}
        </button>
      </form>
    </AuthLayout>
  );
}
