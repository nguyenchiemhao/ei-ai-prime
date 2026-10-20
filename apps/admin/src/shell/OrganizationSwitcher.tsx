import { useId } from "react";
import { useTranslation } from "react-i18next";
import { Chevron } from "./Chevron";
import { initials } from "./initials";
import { useMenu } from "./useMenu";

/** The user's Organization. A user belongs to exactly one, so the menu has one (current) item. */
export function OrganizationSwitcher({ name }: { name: string }) {
  const { t } = useTranslation();
  const { open, setOpen, close, rootRef, buttonRef, onKeyDown } = useMenu();
  const menuId = useId();
  return (
    <div className="menu-root" ref={rootRef} onKeyDown={onKeyDown}>
      <button
        type="button"
        ref={buttonRef}
        className="switcher"
        data-testid="org-switcher"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen(!open)}
      >
        <span className="switcher-avatar" aria-hidden="true">
          {initials(name)}
        </span>
        <span className="switcher-text">
          <span className="switcher-label">{t("admin.shell.organization")}</span>
          <span className="switcher-value">{name}</span>
        </span>
        <Chevron />
      </button>
      {open ? (
        <div className="menu" role="menu" id={menuId}>
          <button
            type="button"
            role="menuitemradio"
            aria-checked="true"
            className="menu-item"
            onClick={close}
          >
            {name}
          </button>
        </div>
      ) : null}
    </div>
  );
}
