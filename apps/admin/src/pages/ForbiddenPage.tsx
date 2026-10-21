import { useTranslation } from "react-i18next";
import { usePageTitle } from "../components/usePageTitle";

/** An area the caller's role does not include, shown inside the shell (the Sidebar stays). */
export function ForbiddenPage() {
  const { t } = useTranslation();
  usePageTitle(t("admin.forbidden.title"));
  return (
    <main className="area-page" data-testid="area-forbidden">
      <h1 className="area-title">{t("admin.forbidden.title")}</h1>
      <p className="area-text">{t("admin.forbidden.text")}</p>
    </main>
  );
}
