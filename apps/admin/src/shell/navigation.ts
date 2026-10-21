import type { Permission } from "../api/permissions";

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
  /** The area is shown to a user holding any of these permissions (docs/architecture/rbac.md). */
  anyOf: readonly Permission[];
}

function area(slug: AreaSlug, group: GroupKey, anyOf: readonly Permission[]): Area {
  return { slug, labelKey: `admin.shell.area.${slug}`, group, anyOf };
}

/** The Sidebar items in display order (Sidebar artboard, without Chat). */
export const AREAS: readonly Area[] = [
  area("dashboard", "overview", ["dashboard.view"]),
  area("assistants", "build", ["assistants.manage"]),
  area("knowledge", "build", ["knowledge.manage"]),
  area("answer-scripts", "build", ["knowledge.manage"]),
  area("glossary", "build", ["knowledge.manage"]),
  area("skills", "build", ["assistants.manage", "connectors.manage"]),
  area("channels", "deploy", ["assistants.manage", "connectors.manage"]),
  area("conversations", "review", ["conversations.read"]),
  area("unanswered", "review", ["conversations.read"]),
  area("members", "settings", ["members.view"]),
  area("organization", "settings", ["org.settings.manage"]),
];

export function findArea(slug: string | undefined): Area | undefined {
  return AREAS.find((candidate) => candidate.slug === slug);
}

export function isAreaSlug(slug: string | undefined): slug is AreaSlug {
  return findArea(slug) !== undefined;
}

/** The areas a user holding `permissions` may open, in Sidebar order. */
export function visibleAreas(permissions: readonly string[]): Area[] {
  return AREAS.filter((candidate) =>
    candidate.anyOf.some((permission) => permissions.includes(permission)),
  );
}

/** The path of an area inside a Workspace. */
export function areaPath(workspaceId: string, slug: AreaSlug): string {
  return `/w/${workspaceId}/${slug}`;
}
