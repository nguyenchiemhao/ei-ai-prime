import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { type ApiState, fetchApiState } from "./api";
import { LANGUAGES, type Language } from "./i18n";

export function App() {
  const { t, i18n } = useTranslation();
  const [api, setApi] = useState<ApiState | "checking">("checking");
  const language = i18n.resolvedLanguage ?? "en";

  useEffect(() => {
    const controller = new AbortController();
    void fetchApiState(controller.signal).then((state) => {
      if (!controller.signal.aborted) setApi(state);
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  return (
    <main className="app">
      <h1 className="app__title">{t("common.productName")}</h1>
      <p className="app__subtitle">{t("admin.title")}</p>
      <section className="app__card">
        <span className="app__status" data-state={api} role="status">
          {t(`admin.api.${api}`)}
        </span>
        <select
          className="app__language"
          aria-label={t("common.language.label")}
          value={language}
          onChange={(event) => void i18n.changeLanguage(event.target.value as Language)}
        >
          {LANGUAGES.map((code) => (
            <option key={code} value={code}>
              {t(`common.language.${code}`)}
            </option>
          ))}
        </select>
      </section>
    </main>
  );
}

// Deliberate lint error to prove CI fails (EA-13 AC3); reverted in the next commit.
const ciLintProbe = 1;
