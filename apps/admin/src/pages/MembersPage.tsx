import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { type AssignableRole, changeMemberRole, listMembers, type Member } from "../api/members";
import { can } from "../api/permissions";
import { useSession } from "../auth/SessionProvider";
import { usePageTitle } from "../components/usePageTitle";
import { InviteDialog } from "../members/InviteDialog";
import { MembersTable } from "../members/MembersTable";
import { RoleMatrix } from "../members/RoleMatrix";
import { useWorkspaceAccess } from "../shell/WorkspaceAccessContext";
import "../members/members.css";

const FORBIDDEN = 403;
const UNAUTHENTICATED = 401;

function errorKey(status: number): string {
  return status === FORBIDDEN ? "admin.members.error.forbidden" : "admin.members.error.generic";
}

/**
 * Members & roles (Members artboard): who is in this Workspace with which role, the role matrix,
 * and for managers an invitation and a role select per row. What the caller may do comes from the
 * permissions the API reported for this Workspace; the API checks every change again.
 */
export function MembersPage() {
  const { t } = useTranslation();
  const { access, refresh } = useWorkspaceAccess();
  const { session, refresh: refreshSession } = useSession();
  usePageTitle(t("admin.members.title"));
  const [members, setMembers] = useState<Member[] | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Record<string, AssignableRole>>({});
  const [inviting, setInviting] = useState(false);
  const inviteButton = useRef<HTMLButtonElement>(null);
  const canManage = can(access, "members.manage");

  useEffect(() => {
    let cancelled = false;
    void listMembers(access.id).then((result) => {
      if (cancelled) return;
      if (result.ok) setMembers(result.data);
      else if (result.status === UNAUTHENTICATED) void refreshSession();
      else setError(t(errorKey(result.status)));
    });
    return () => {
      cancelled = true;
    };
  }, [access.id, t, refreshSession]);

  // The caller cannot lock themselves out: their own row is editable only with an Organization role.
  const editable = (member: Member) =>
    canManage && (member.user_id !== session?.user.id || access.org_role !== null);

  async function changeRole(member: Member, role: AssignableRole) {
    setPending((current) => ({ ...current, [member.user_id]: role }));
    setStatus(null);
    setError(null);
    const result = await changeMemberRole(access.id, member.user_id, role);
    setPending((current) => {
      const rest = { ...current };
      delete rest[member.user_id];
      return rest;
    });
    if (!result.ok) {
      if (result.status === UNAUTHENTICATED) {
        void refreshSession();
        return;
      }
      setError(t(errorKey(result.status)));
      return;
    }
    setMembers((current) =>
      (current ?? []).map((item) => (item.user_id === member.user_id ? result.data : item)),
    );
    setStatus(t("admin.members.status.updated"));
    if (member.user_id === session?.user.id) refresh();
  }

  function closeInvite() {
    setInviting(false);
    inviteButton.current?.focus();
  }

  function invited(member: Member) {
    setMembers((current) => [...(current ?? []), member]);
    setStatus(t("admin.members.status.invited", { email: member.email }));
    setError(null);
    closeInvite();
  }

  return (
    <main className="area-page members-page" data-testid="members-page">
      <header className="members-header">
        <div>
          <h1 className="area-title">{t("admin.members.title")}</h1>
          <p className="members-subtitle">
            {t("admin.members.subtitle", { workspace: access.name })}
          </p>
        </div>
        {canManage ? (
          <button
            type="button"
            ref={inviteButton}
            className="button-primary"
            data-testid="invite-member"
            onClick={() => setInviting(true)}
          >
            {t("admin.members.invite")}
          </button>
        ) : null}
      </header>
      {status ? (
        <p className="members-status" role="status" data-testid="members-status">
          {status}
        </p>
      ) : null}
      {error ? (
        <p className="members-alert" role="alert" data-testid="members-error">
          {error}
        </p>
      ) : null}
      {members ? (
        <section className="members-card members-card-flush">
          <MembersTable
            members={members}
            workspaceName={access.name}
            editable={editable}
            pending={pending}
            onChangeRole={(member, role) => void changeRole(member, role)}
          />
        </section>
      ) : null}
      <RoleMatrix />
      {inviting ? (
        <InviteDialog
          workspaceId={access.id}
          onClose={closeInvite}
          onInvited={invited}
          onSessionExpired={() => void refreshSession()}
        />
      ) : null}
    </main>
  );
}
