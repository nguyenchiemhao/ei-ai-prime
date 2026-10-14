import en from "@ei-ai/i18n/en.json";
import vi from "@ei-ai/i18n/vi.json";
import i18next, { type i18n } from "i18next";
import { initReactI18next } from "react-i18next";

export const LANGUAGES = ["en", "vi"] as const;
export type Language = (typeof LANGUAGES)[number];

/** A fresh i18n instance (the admin UI is English by default, UI3). */
export function createI18n(language: Language = "en"): i18n {
  const instance = i18next.createInstance();
  void instance.use(initReactI18next).init({
    resources: { en: { translation: en }, vi: { translation: vi } },
    lng: language,
    fallbackLng: "en",
    initAsync: false,
    interpolation: { escapeValue: false },
  });
  return instance;
}
