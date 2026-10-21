import { useId } from "react";
import { useTranslation } from "react-i18next";
import type { WorkspaceInfo } from "../api/workspaces";
import { useSignOut } from "../auth/useSignOut";
import { initials } from "./initials";
import { useMenu } from "./useMenu";

/**
 * The signed-in user with their role in the current Workspace (else their Organization role);
 * the menu holds "Sign out".
 */
export function UserMenu({ name, workspace }: { name: string; workspace: WorkspaceInfo }) {
  const { t } = useTranslation();
  const roleLabel = workspace.role
    ? t(`admin.shell.role.${workspace.role}`, { defaultValue: workspace.role })
    : workspace.org_role
      ? t(`admin.shell.orgRole.${workspace.org_role}`, { defaultValue: workspace.org_role })
      : "";
  const signOut = useSignOut();
  const { open, setOpen, rootRef, buttonRef, onKeyDown } = useMenu();
  const menuId = useId();
  return (
    <div className="menu-root user-root" ref={rootRef} onKeyDown={onKeyDown}>
      <button
        type="button"
        ref={buttonRef}
        className="user-button"
        data-testid="user-menu"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen(!open)}
      >
        <span className="user-avatar" aria-hidden="true">
          {initials(name)}
        </span>
        <span className="switcher-text">
          <span className="user-name">{name}</span>
          <span className="user-role">{roleLabel}</span>
        </span>
      </button>
      {open ? (
        <div className="menu menu-up" role="menu" id={menuId}>
          <button
            type="button"
            role="menuitem"
            className="menu-item"
            onClick={() => void signOut()}
          >
            {t("admin.shell.signOut")}
          </button>
        </div>
      ) : null}
    </div>
  );
}
