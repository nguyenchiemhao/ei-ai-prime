import type { components } from "@ei-ai/api-types";
import { type ApiResult, apiRequest, clearCsrfToken } from "./client";

export type SessionInfo = components["schemas"]["SessionInfo"];
export type SessionWorkspace = components["schemas"]["SessionWorkspace"];

export function getSession(): Promise<ApiResult<SessionInfo>> {
  return apiRequest<SessionInfo>("GET", "/auth/session");
}

export async function signIn(
  email: string,
  password: string,
): Promise<ApiResult<{ default_workspace_id: string | null }>> {
  const result = await apiRequest<{ default_workspace_id: string | null }>(
    "POST",
    "/auth/sign-in",
    { email, password },
  );
  clearCsrfToken();
  return result;
}

export async function signOut(): Promise<ApiResult<void>> {
  const result = await apiRequest<void>("POST", "/auth/sign-out");
  clearCsrfToken();
  return result;
}

export function forgotPassword(email: string): Promise<ApiResult<void>> {
  return apiRequest<void>("POST", "/auth/forgot-password", { email });
}

export function setPassword(token: string, password: string): Promise<ApiResult<void>> {
  return apiRequest<void>("POST", "/auth/set-password", { token, password });
}
