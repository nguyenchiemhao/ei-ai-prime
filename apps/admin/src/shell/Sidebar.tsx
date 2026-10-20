import { useId } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import type { WorkspaceAccess } from "../api/workspaces";
import { useSession } from "../auth/SessionProvider";
import { Logo } from "../components/Logo";
import { AREAS, type AreaSlug, areaPath, GROUPS } from "./navigation";
import { OrganizationSwitcher } from "./OrganizationSwitcher";
import { UserMenu } from "./UserMenu";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";

const ARIA_CURRENT_PAGE = "page";

function NavGroup({
  group,
  workspaceId,
  active,
}: {
  group: (typeof GROUPS)[number];
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
      {AREAS.filter((area) => area.group === group).map((area) => (
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

/** The admin console navigation (Sidebar artboard) for one verified Workspace. */
export function Sidebar({ workspace, area }: { workspace: WorkspaceAccess; area: AreaSlug }) {
  const { t } = useTranslation();
  const { session } = useSession();
  if (!session) return null;
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
      {GROUPS.map((group) => (
        <NavGroup key={group} group={group} workspaceId={workspace.id} active={area} />
      ))}
      <UserMenu name={session.user.display_name} role={workspace.role} />
    </nav>
  );
}
