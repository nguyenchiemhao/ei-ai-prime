import { useEffect } from "preact/hooks";
import { createTranslator, languageFromNavigator } from "./i18n";

export function App() {
  const language = languageFromNavigator(navigator.language);
  const t = createTranslator(language);

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  return (
    <div class="widget">
      <header class="widget__header">
        <h1 class="widget__title">{t("common.productName")}</h1>
      </header>
      <p class="widget__greeting">{t("widget.greeting")}</p>
      <div
        class="widget__conversation"
        role="log"
        aria-live="polite"
        aria-label={t("widget.conversationLabel")}
      />
    </div>
  );
}
