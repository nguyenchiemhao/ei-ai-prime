import { useTranslation } from "react-i18next";
import { usePageTitle } from "../components/usePageTitle";
import { findArea } from "../shell/navigation";

/** Placeholder content of a Sidebar area until its own ticket lands. */
export function AreaPage({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const label = t(findArea(slug)?.labelKey ?? "");
  usePageTitle(label);
  return (
    <main className="area-page" data-testid="area-page" data-area={slug}>
      <h1 className="area-title">{label}</h1>
      <p className="area-text">{t("admin.shell.empty")}</p>
    </main>
  );
}
