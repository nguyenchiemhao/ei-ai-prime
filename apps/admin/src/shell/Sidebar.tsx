import { useId } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import type { WorkspaceInfo } from "../api/workspaces";
import { useSession } from "../auth/SessionProvider";
import { Logo } from "../components/Logo";
import { type Area, type AreaSlug, areaPath, GROUPS, visibleAreas } from "./navigation";
import { OrganizationSwitcher } from "./OrganizationSwitcher";
import { UserMenu } from "./UserMenu";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";

const ARIA_CURRENT_PAGE = "page";

function NavGroup({
  group,
  areas,
  workspaceId,
  active,
}: {
  group: (typeof GROUPS)[number];
  areas: readonly Area[];
  workspaceId: string;
  active: AreaSlug;
}) {
  const { t } = useTranslation();
  const headingId = useId();
  return (
    <div className="nav-group" role="group" aria-labelledby={headingId}>
      <div className="nav-heading" id={headingId}>
        {t(`admin.shell.group.${group}`)}
      </div>
      {areas.map((area) => (
        <Link
          key={area.slug}
          to={areaPath(workspaceId, area.slug)}
          className="nav-item"
          aria-current={area.slug === active ? ARIA_CURRENT_PAGE : undefined}
        >
          {t(area.labelKey)}
        </Link>
      ))}
    </div>
  );
}

/**
 * The admin console navigation (Sidebar artboard) for one verified Workspace. It lists only the
 * areas the caller's permissions allow and no heading without an item; hiding is a convenience,
 * the API checks every call.
 */
export function Sidebar({ workspace, area }: { workspace: WorkspaceInfo; area: AreaSlug }) {
  const { t } = useTranslation();
  const { session } = useSession();
  if (!session) return null;
  const visible = visibleAreas(workspace.permissions);
  return (
    <nav className="sidebar" data-testid="sidebar" aria-label={t("admin.shell.navLabel")}>
      <div className="sidebar-top">
        <Logo />
        <span className="sidebar-tag">{t("admin.shell.prototype")}</span>
      </div>
      <div className="switchers">
        <OrganizationSwitcher name={session.organization.name} />
        <WorkspaceSwitcher current={workspace} area={area} />
      </div>
      {GROUPS.map((group) => {
        const areas = visible.filter((candidate) => candidate.group === group);
        return areas.length === 0 ? null : (
          <NavGroup
            key={group}
            group={group}
            areas={areas}
            workspaceId={workspace.id}
            active={area}
          />
        );
      })}
      <UserMenu name={session.user.display_name} workspace={workspace} />
    </nav>
  );
}
