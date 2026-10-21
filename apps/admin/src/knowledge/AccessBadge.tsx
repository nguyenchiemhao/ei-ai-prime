import { useTranslation } from "react-i18next";
import { accessLabel, isAccessLevel } from "./labels";

interface Props {
  level: string;
  groups?: readonly string[];
}

/** Access badge: colour from the access tokens, and always the level as text. */
export function AccessBadge({ level, groups = [] }: Props) {
  const { t } = useTranslation();
  return (
    <span
      className="access-badge"
      data-testid="access-badge"
      data-access={isAccessLevel(level) ? level : "unknown"}
    >
      {accessLabel(t, { access_level: level, groups })}
    </span>
  );
}
