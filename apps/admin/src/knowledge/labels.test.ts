import { describe, expect, it } from "vitest";
import { accessLabel, matchesSearch } from "./labels";

const t = (key: string) =>
  ({
    "admin.knowledge.access.public": "Public",
    "admin.knowledge.access.authenticated": "Authenticated",
    "admin.knowledge.access.restricted": "Restricted",
  })[key] ?? key;

describe("accessLabel", () => {
  it("returns_the_level_name_for_public_and_authenticated", () => {
    expect(accessLabel(t, { access_level: "public", groups: [] })).toBe("Public");
    expect(accessLabel(t, { access_level: "authenticated", groups: [] })).toBe("Authenticated");
  });

  it("appends_the_groups_in_stored_order_for_restricted", () => {
    expect(accessLabel(t, { access_level: "restricted", groups: ["g1", "g2"] })).toBe(
      "Restricted · g1, g2",
    );
  });

  it("falls_back_to_the_raw_value_for_an_unknown_level", () => {
    expect(accessLabel(t, { access_level: "secret", groups: [] })).toBe("secret");
  });
});

describe("matchesSearch", () => {
  const item = { name: "Quỹ lương", subtitle: "Client: Japan · under NDA" };

  it("ignores_case_and_diacritics", () => {
    expect(matchesSearch(item, "quy luong")).toBe(true);
    expect(matchesSearch(item, "QUỸ")).toBe(true);
  });

  it("matches_the_subtitle", () => {
    expect(matchesSearch(item, "japan")).toBe(true);
  });

  it("matches_everything_for_an_empty_query_and_handles_a_missing_subtitle", () => {
    expect(matchesSearch({ name: "A", subtitle: null }, "  ")).toBe(true);
    expect(matchesSearch({ name: "A", subtitle: null }, "b")).toBe(false);
  });
});
