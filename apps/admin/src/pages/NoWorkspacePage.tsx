import { useTranslation } from "react-i18next";
import { useSignOut } from "../auth/useSignOut";
import { AuthLayout } from "../components/AuthLayout";
import { usePageTitle } from "../components/usePageTitle";

/** A signed-in user who belongs to no Workspace yet. */
export function NoWorkspacePage() {
  const { t } = useTranslation();
  const signOut = useSignOut();
  usePageTitle(t("admin.noWorkspace.title"));
  return (
    <AuthLayout>
      <section className="auth-card" data-testid="no-workspace">
        <div className="auth-head">
          <h1 className="auth-title">{t("admin.noWorkspace.title")}</h1>
          <p className="auth-text">{t("admin.noWorkspace.text")}</p>
        </div>
        <button type="button" className="auth-button" onClick={() => void signOut()}>
          {t("admin.shell.signOut")}
        </button>
      </section>
    </AuthLayout>
  );
}
