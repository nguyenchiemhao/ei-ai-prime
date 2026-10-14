import en from "@ei-ai/i18n/en.json";
import vi from "@ei-ai/i18n/vi.json";

export type Language = "en" | "vi";
export type Translate = (key: string) => string;

const catalogs: Record<Language, unknown> = { en, vi };

/** "vi" for any vi-* browser language, English otherwise. */
export function languageFromNavigator(language: string | undefined): Language {
  return language?.toLowerCase().startsWith("vi") ? "vi" : "en";
}

/** Dictionary lookup by dotted key. A missing entry returns the key itself; it never throws. */
export function createTranslator(language: Language): Translate {
  return (key) => {
    let node: unknown = catalogs[language];
    for (const part of key.split(".")) {
      if (typeof node !== "object" || node === null) return key;
      node = (node as Record<string, unknown>)[part];
    }
    return typeof node === "string" ? node : key;
  };
}
