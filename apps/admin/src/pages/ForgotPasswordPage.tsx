import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { forgotPassword } from "../api/auth";
import { AuthLayout } from "../components/AuthLayout";
import { AUTOCOMPLETE, TextField } from "../components/TextField";
import { usePageTitle } from "../components/usePageTitle";
import { PATHS } from "../paths";

const ERROR_ID = "forgot-password-error";

export function ForgotPasswordPage() {
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [emailError, setEmailError] = useState<string | undefined>();
  const [error, setError] = useState<string | undefined>();
  const [sent, setSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  usePageTitle(t("admin.forgot.title"));

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    const nextEmailError = email.trim() ? undefined : t("admin.signIn.emailRequired");
    setEmailError(nextEmailError);
    setError(undefined);
    if (nextEmailError) return;

    setSubmitting(true);
    const result = await forgotPassword(email.trim());
    setSubmitting(false);
    if (result.ok) setSent(true);
    else if (result.status === 429) setError(t("admin.signIn.rateLimited"));
    else setError(t("admin.signIn.unavailable"));
  }

  const back = (
    <Link className="auth-link" to={PATHS.signIn}>
      {t("admin.forgot.back")}
    </Link>
  );

  return (
    <AuthLayout>
      <div className="auth-card">
        <div className="auth-head">
          <h1 className="auth-title">{t("admin.forgot.title")}</h1>
          <p className="auth-text">{t("admin.forgot.text")}</p>
        </div>
        {sent ? (
          <p className="auth-notice" role="status" data-testid="forgot-password-confirmation">
            {t("admin.forgot.confirmation")}
          </p>
        ) : (
          <form className="auth-card-form" noValidate onSubmit={(event) => void onSubmit(event)}>
            <TextField
              id="forgot-email"
              label={t("admin.signIn.email")}
              type="email"
              autoComplete={AUTOCOMPLETE.username}
              value={email}
              onChange={setEmail}
              error={emailError}
              describedBy={error ? ERROR_ID : undefined}
            />
            {error ? (
              <p id={ERROR_ID} className="auth-alert" role="alert">
                {error}
              </p>
            ) : null}
            <button className="auth-button" type="submit" disabled={submitting}>
              {t("admin.forgot.submit")}
            </button>
          </form>
        )}
        {back}
      </div>
    </AuthLayout>
  );
}
