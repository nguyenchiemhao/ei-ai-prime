import en from "@ei-ai/i18n/en.json";
import { describe, expect, it } from "vitest";
import { AREAS, GROUPS, isAreaSlug } from "./navigation";

function lookup(key: string): unknown {
  return key
    .split(".")
    .reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], en);
}

describe("navigation", () => {
  it("lists_eleven_areas_in_contract_order", () => {
    expect(AREAS.map((area) => area.slug)).toEqual([
      "dashboard",
      "assistants",
      "knowledge",
      "answer-scripts",
      "glossary",
      "skills",
      "channels",
      "conversations",
      "unanswered",
      "members",
      "organization",
    ]);
  });

  it("groups_areas_under_five_headings_and_has_no_chat", () => {
    expect(GROUPS).toEqual(["overview", "build", "deploy", "review", "settings"]);
    expect(AREAS.filter((area) => area.group === "build")).toHaveLength(5);
    expect(isAreaSlug("chat")).toBe(false);
    expect(isAreaSlug("glossary")).toBe(true);
  });

  it("has_an_english_label_for_every_area_and_group", () => {
    for (const area of AREAS) expect(typeof lookup(area.labelKey)).toBe("string");
    for (const group of GROUPS) expect(typeof lookup(`admin.shell.group.${group}`)).toBe("string");
  });
});
