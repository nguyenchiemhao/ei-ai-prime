import type { components } from "@ei-ai/api-types";
import { type ApiResult, apiRequest } from "./client";

export type WorkspaceAccess = components["schemas"]["SessionWorkspace"];

export function getWorkspace(id: string): Promise<ApiResult<WorkspaceAccess>> {
  return apiRequest<WorkspaceAccess>("GET", `/workspaces/${encodeURIComponent(id)}`);
}
