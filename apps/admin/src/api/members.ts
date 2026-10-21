import type { components } from "@ei-ai/api-types";
import { type ApiResult, apiRequest } from "./client";

export type Member = components["schemas"]["MemberItem"];
export type AssignableRole = components["schemas"]["WorkspaceRoleRequest"]["role"];

/** The roles an admin can give, in the order of the role select (the six of the matrix). */
export const ASSIGNABLE_ROLES: readonly AssignableRole[] = [
  "workspace_admin",
  "developer",
  "builder",
  "knowledge_editor",
  "reviewer",
  "viewer",
];

const members = (workspaceId: string) => `/workspaces/${encodeURIComponent(workspaceId)}/members`;

export async function listMembers(workspaceId: string): Promise<ApiResult<Member[]>> {
  const result = await apiRequest<{ members: Member[] }>("GET", members(workspaceId));
  return result.ok ? { ok: true, data: result.data.members } : result;
}

export function inviteMember(
  workspaceId: string,
  body: { email: string; display_name?: string; role: AssignableRole },
): Promise<ApiResult<Member>> {
  return apiRequest<Member>("POST", members(workspaceId), body);
}

export function changeMemberRole(
  workspaceId: string,
  userId: string,
  role: AssignableRole,
): Promise<ApiResult<Member>> {
  return apiRequest<Member>("PUT", `${members(workspaceId)}/${encodeURIComponent(userId)}`, {
    role,
  });
}
