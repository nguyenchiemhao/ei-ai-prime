import { useId } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import type { WorkspaceInfo } from "../api/workspaces";
import { useSession } from "../auth/SessionProvider";
import { Chevron } from "./Chevron";
import { type AreaSlug, areaPath } from "./navigation";
import { useMenu } from "./useMenu";

/** Lists only the Workspaces the signed-in user belongs to; choosing one keeps the current area. */
export function WorkspaceSwitcher({ current, area }: { current: WorkspaceInfo; area: AreaSlug }) {
  const { t } = useTranslation();
  const { session } = useSession();
  const navigate = useNavigate();
  const { open, setOpen, rootRef, buttonRef, onKeyDown } = useMenu();
  const menuId = useId();
  const workspaces = [...(session?.workspaces ?? [])].sort((a, b) => a.name.localeCompare(b.name));

  function choose(id: string) {
    setOpen(false);
    if (id !== current.id) void navigate(areaPath(id, area));
  }

  return (
    <div className="menu-root" ref={rootRef} onKeyDown={onKeyDown}>
      <button
        type="button"
        ref={buttonRef}
        className="switcher switcher-workspace"
        data-testid="workspace-switcher"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen(!open)}
      >
        <span className="switcher-text">
          <span className="switcher-label">{t("admin.shell.workspace")}</span>
          <span className="switcher-value">{current.name}</span>
        </span>
        <Chevron />
      </button>
      {open ? (
        <div className="menu" role="menu" id={menuId}>
          {workspaces.map((workspace) => (
            <button
              key={workspace.id}
              type="button"
              role="menuitemradio"
              aria-checked={workspace.id === current.id}
              className="menu-item"
              onClick={() => choose(workspace.id)}
            >
              {workspace.name}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
