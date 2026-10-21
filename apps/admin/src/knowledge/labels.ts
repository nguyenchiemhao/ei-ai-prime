export type AccessLevel = "public" | "authenticated" | "restricted";

type Translate = (key: string) => string;

const LEVELS: readonly string[] = ["public", "authenticated", "restricted"];

/** Narrows the API's plain string to one of the three known access levels. */
export function isAccessLevel(value: string): value is AccessLevel {
  return LEVELS.includes(value);
}

/** Text of an access badge, e.g. "Restricted · g1, g2" (groups in stored order). */
export function accessLabel(
  t: Translate,
  item: { access_level: string; groups: readonly string[] },
): string {
  if (!isAccessLevel(item.access_level)) return item.access_level;
  const name = t(`admin.knowledge.access.${item.access_level}`);
  if (item.access_level !== "restricted" || item.groups.length === 0) return name;
  return `${name} · ${item.groups.join(", ")}`;
}

/** Lower-cases and strips diacritics so "Quỹ" and "quy" compare equal. */
function fold(value: string): string {
  return value.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

/** Whether a collection matches the search box (name and subtitle, case and diacritics ignored). */
export function matchesSearch(
  item: { name: string; subtitle: string | null },
  query: string,
): boolean {
  const needle = fold(query.trim());
  if (needle === "") return true;
  return fold(`${item.name} ${item.subtitle ?? ""}`).includes(needle);
}
