import { useLayoutEffect } from "react";
import { useTranslation } from "react-i18next";

/** Sets the document title to "<title> · ei-ai". */
export function usePageTitle(title: string): void {
  const { t } = useTranslation();
  const full = t("admin.documentTitle", { title });
  useLayoutEffect(() => {
    document.title = full;
  }, [full]);
}
