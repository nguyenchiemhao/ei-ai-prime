import { useId } from "react";
import { useTranslation } from "react-i18next";
import { MATRIX_ROLES, ROLE_MATRIX } from "./matrixData";

/** "What each role can do" (Members artboard): the grid, sensitive rows highlighted, the footnote. */
export function RoleMatrix() {
  const { t } = useTranslation();
  const titleId = useId();
  return (
    <section className="members-card" aria-labelledby={titleId}>
      <h2 className="members-card-title" id={titleId}>
        {t("admin.members.matrix.title")}
      </h2>
      <div className="members-scroll">
        <table
          className="members-table role-matrix"
          data-testid="role-matrix"
          aria-labelledby={titleId}
        >
          <thead>
            <tr>
              <th scope="col">{t("admin.members.matrix.permissionColumn")}</th>
              {MATRIX_ROLES.map((role) => (
                <th scope="col" key={role}>
                  {role === "workspace_admin"
                    ? t("admin.members.matrix.admin")
                    : t(`admin.shell.role.${role}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROLE_MATRIX.map((row) => (
              <tr
                key={row.permission}
                data-testid="matrix-row"
                data-permission={row.permission}
                data-sensitive={row.sensitive}
              >
                <td className="matrix-label">{t(row.labelKey)}</td>
                {row.grants.map((granted, index) =>
                  granted ? (
                    <td key={MATRIX_ROLES[index]}>{t("admin.members.matrix.yes")}</td>
                  ) : (
                    <td key={MATRIX_ROLES[index]} aria-label={t("admin.members.matrix.no")}>
                      <span aria-hidden="true">—</span>
                    </td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="members-note" data-testid="role-matrix-note">
        {t("admin.members.matrix.note")}
      </p>
    </section>
  );
}
