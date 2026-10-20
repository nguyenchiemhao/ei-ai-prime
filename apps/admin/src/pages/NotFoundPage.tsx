import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { AuthLayout } from "../components/AuthLayout";
import { usePageTitle } from "../components/usePageTitle";
import { PATHS } from "../paths";

/** Unknown path, or a Workspace the user cannot see. Shows nothing about the requested Workspace. */
export function NotFoundPage() {
  const { t } = useTranslation();
  usePageTitle(t("admin.notFound.title"));
  return (
    <AuthLayout>
      <section className="auth-card" data-testid="not-found">
        <div className="auth-head">
          <h1 className="auth-title">{t("admin.notFound.title")}</h1>
          <p className="auth-text">{t("admin.notFound.text")}</p>
        </div>
        <Link className="auth-link" to={PATHS.root}>
          {t("admin.notFound.link")}
        </Link>
      </section>
    </AuthLayout>
  );
}
