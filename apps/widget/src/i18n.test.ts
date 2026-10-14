import { describe, expect, it } from "vitest";
import { createTranslator, languageFromNavigator } from "./i18n";

describe("i18n", () => {
  it("t_returns_key_for_missing_entry_and_never_throws", () => {
    const t = createTranslator("en");

    expect(t("widget.doesNotExist")).toBe("widget.doesNotExist");
    expect(t("widget")).toBe("widget");
    expect(t("")).toBe("");
    expect(t("common.productName.deeper")).toBe("common.productName.deeper");
  });

  it("t_reads_the_shared_catalog", () => {
    expect(createTranslator("en")("widget.greeting")).toBe("Hello! How can I help you today?");
    expect(createTranslator("vi")("common.language.label")).toBe("Ngôn ngữ");
  });

  it("picks_vietnamese_for_vi_browser_languages_and_english_otherwise", () => {
    expect(languageFromNavigator("vi")).toBe("vi");
    expect(languageFromNavigator("vi-VN")).toBe("vi");
    expect(languageFromNavigator("en-US")).toBe("en");
    expect(languageFromNavigator("fr")).toBe("en");
    expect(languageFromNavigator(undefined)).toBe("en");
  });
});
