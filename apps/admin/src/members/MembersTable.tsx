import { useTranslation } from "react-i18next";
import { ASSIGNABLE_ROLES, type AssignableRole, type Member } from "../api/members";
import { lastActive } from "./lastActive";

interface Props {
  members: readonly Member[];
  workspaceName: string;
  /** Whether the caller may change this member's role with a select. */
  editable: (member: Member) => boolean;
  /** Role changes in flight by user id: that select shows the chosen role until the answer. */
  pending: Readonly<Record<string, AssignableRole>>;
  onChangeRole(member: Member, role: AssignableRole): void;
}

function isAssignable(role: string): role is AssignableRole {
  return (ASSIGNABLE_ROLES as readonly string[]).includes(role);
}

function LastActiveText({ iso }: { iso: string | null }) {
  const { t } = useTranslation();
  const value = lastActive(iso, new Date());
  return (
    <>
      {value.key === "daysAgo"
        ? t("admin.members.lastActive.daysAgo", { days: value.days })
        : t(`admin.members.lastActive.${value.key}`)}
    </>
  );
}

/** The Members table (Members artboard): member, role in this Workspace, last active. */
export function MembersTable({ members, workspaceName, editable, pending, onChangeRole }: Props) {
  const { t } = useTranslation();
  return (
    <div className="members-scroll">
      <table
        className="members-table"
        data-testid="members-table"
        aria-label={t("admin.members.tableLabel")}
      >
        <thead>
          <tr>
            <th scope="col">{t("admin.members.column.member")}</th>
            <th scope="col">{t("admin.members.column.role", { workspace: workspaceName })}</th>
            <th scope="col">{t("admin.members.column.lastActive")}</th>
          </tr>
        </thead>
        <tbody>
          {members.map((member) => (
            <tr key={member.user_id} data-testid="member-row" data-user-id={member.user_id}>
              <td>
                <div className="member-name">{member.display_name}</div>
                <div className="member-meta">{member.email}</div>
                {member.org_role ? (
                  <div className="member-meta" data-testid="member-org-role">
                    {t(`admin.shell.orgRole.${member.org_role}`, { defaultValue: member.org_role })}
                  </div>
                ) : null}
              </td>
              <td>
                {editable(member) && isAssignable(member.role) ? (
                  <select
                    className="role-select"
                    aria-label={t("admin.members.roleFor", { name: member.display_name })}
                    value={pending[member.user_id] ?? member.role}
                    disabled={member.user_id in pending}
                    onChange={(event) => {
                      const role = event.target.value;
                      if (isAssignable(role)) onChangeRole(member, role);
                    }}
                  >
                    {ASSIGNABLE_ROLES.map((role) => (
                      <option key={role} value={role}>
                        {t(`admin.shell.role.${role}`)}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span data-testid="member-role">
                    {t(`admin.shell.role.${member.role}`, { defaultValue: member.role })}
                  </span>
                )}
              </td>
              <td data-testid="member-last-active">
                <LastActiveText iso={member.last_active_at} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
