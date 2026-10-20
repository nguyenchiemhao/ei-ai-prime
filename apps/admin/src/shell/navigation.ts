export const GROUPS = ["overview", "build", "deploy", "review", "settings"] as const;
export type GroupKey = (typeof GROUPS)[number];

export type AreaSlug =
  | "dashboard"
  | "assistants"
  | "knowledge"
  | "answer-scripts"
  | "glossary"
  | "skills"
  | "channels"
  | "conversations"
  | "unanswered"
  | "members"
  | "organization";

export interface Area {
  slug: AreaSlug;
  labelKey: string;
  group: GroupKey;
}

function area(slug: AreaSlug, group: GroupKey): Area {
  return { slug, labelKey: `admin.shell.area.${slug}`, group };
}

/** The Sidebar items in display order (Sidebar artboard, without Chat). */
export const AREAS: readonly Area[] = [
  area("dashboard", "overview"),
  area("assistants", "build"),
  area("knowledge", "build"),
  area("answer-scripts", "build"),
  area("glossary", "build"),
  area("skills", "build"),
  area("channels", "deploy"),
  area("conversations", "review"),
  area("unanswered", "review"),
  area("members", "settings"),
  area("organization", "settings"),
];

export function findArea(slug: string | undefined): Area | undefined {
  return AREAS.find((candidate) => candidate.slug === slug);
}

export function isAreaSlug(slug: string | undefined): slug is AreaSlug {
  return findArea(slug) !== undefined;
}

/** The path of an area inside a Workspace. */
export function areaPath(workspaceId: string, slug: AreaSlug): string {
  return `/w/${workspaceId}/${slug}`;
}
