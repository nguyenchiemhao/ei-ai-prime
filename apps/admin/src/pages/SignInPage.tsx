import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation, useNavigate } from "react-router";
import { signIn } from "../api/auth";
import { AuthLayout } from "../components/AuthLayout";
import { AUTOCOMPLETE, TextField } from "../components/TextField";
import { usePageTitle } from "../components/usePageTitle";
import { useSession } from "../auth/SessionProvider";
import { homePath, PATHS } from "../paths";

const ERROR_ID = "sign-in-error";

export function SignInPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { refresh } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [emailError, setEmailError] = useState<string | undefined>();
  const [passwordError, setPasswordError] = useState<string | undefined>();
  const [error, setError] = useState<string | undefined>();
  const [submitting, setSubmitting] = useState(false);
  usePageTitle(t("admin.signIn.title"));

  const notice = (location.state as { notice?: string } | null)?.notice;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    const nextEmailError = email.trim() ? undefined : t("admin.signIn.emailRequired");
    const nextPasswordError = password ? undefined : t("admin.signIn.passwordRequired");
    setEmailError(nextEmailError);
    setPasswordError(nextPasswordError);
    setError(undefined);
    if (nextEmailError || nextPasswordError) return;

    setSubmitting(true);
    const result = await signIn(email.trim(), password);
    if (result.ok) {
      await refresh();
      navigate(homePath(result.data.default_workspace_id), { replace: true });
      return;
    }
    setPassword("");
    if (result.status === 401) setError(t("admin.signIn.invalidCredentials"));
    else if (result.status === 429) setError(t("admin.signIn.rateLimited"));
    else setError(t("admin.signIn.unavailable"));
    setSubmitting(false);
  }

  return (
    <AuthLayout footer={t("admin.signIn.footer")}>
      <form
        className="auth-card"
        data-testid="sign-in-form"
        noValidate
        onSubmit={(event) => void onSubmit(event)}
      >
        <div className="auth-head">
          <h1 className="auth-title">{t("admin.signIn.title")}</h1>
          <p className="auth-text">{t("admin.signIn.subtitle")}</p>
        </div>
        {notice === "passwordSet" ? (
          <p className="auth-notice" role="status" data-testid="sign-in-notice">
            {t("admin.signIn.passwordSetNotice")}
          </p>
        ) : null}
        <TextField
          id="sign-in-email"
          label={t("admin.signIn.email")}
          type="email"
          autoComplete={AUTOCOMPLETE.username}
          value={email}
          onChange={setEmail}
          error={emailError}
        />
        <TextField
          id="sign-in-password"
          label={t("admin.signIn.password")}
          type="password"
          autoComplete={AUTOCOMPLETE.currentPassword}
          value={password}
          onChange={setPassword}
          error={passwordError}
          describedBy={error ? ERROR_ID : undefined}
          aside={
            <Link className="auth-link" to={PATHS.forgotPassword}>
              {t("admin.signIn.forgotLink")}
            </Link>
          }
        />
        {error ? (
          <p id={ERROR_ID} className="auth-alert" role="alert" data-testid="sign-in-error">
            {error}
          </p>
        ) : null}
        <button className="auth-button" type="submit" disabled={submitting}>
          {t("admin.signIn.submit")}
        </button>
      </form>
    </AuthLayout>
  );
}
