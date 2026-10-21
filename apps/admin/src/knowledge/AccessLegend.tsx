import { useTranslation } from "react-i18next";
import { AccessBadge } from "./AccessBadge";
import type { AccessLevel } from "./labels";

const LEVELS: readonly AccessLevel[] = ["public", "authenticated", "restricted"];

/** What the three access levels mean (Collections artboard legend). */
export function AccessLegend() {
  const { t } = useTranslation();
  return (
    <ul className="access-legend" data-testid="access-legend">
      {LEVELS.map((level) => (
        <li key={level} className="access-legend-item">
          <AccessBadge level={level} />
          <span>{t(`admin.knowledge.legend.${level}`)}</span>
        </li>
      ))}
    </ul>
  );
}
