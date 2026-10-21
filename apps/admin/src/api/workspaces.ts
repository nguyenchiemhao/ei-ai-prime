import type { components } from "@ei-ai/api-types";
import { type ApiResult, apiRequest } from "./client";

/** The signed-in user's roles and permissions in one Workspace (`GET /workspaces/{id}`). */
export type WorkspaceInfo = components["schemas"]["WorkspaceInfo"];

export function getWorkspace(id: string): Promise<ApiResult<WorkspaceInfo>> {
  return apiRequest<WorkspaceInfo>("GET", `/workspaces/${encodeURIComponent(id)}`);
}
