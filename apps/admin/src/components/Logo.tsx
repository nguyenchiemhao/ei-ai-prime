import { useTranslation } from "react-i18next";
import "./Logo.css";

const MARK = "ei";

/** The ei-ai mark and product name (SignIn artboard). */
export function Logo() {
  const { t } = useTranslation();
  return (
    <div className="logo">
      <div className="logo-mark" aria-hidden="true">
        {MARK}
      </div>
      <div className="logo-name">{t("common.productName")}</div>
    </div>
  );
}
