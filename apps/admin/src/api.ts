import type { paths } from "@ei-ai/api-types";

type HealthResponse = paths["/healthz"]["get"]["responses"][200]["content"]["application/json"];

export type ApiState = "ok" | "unavailable";

/** Calls the API liveness probe through the same-origin /api proxy. Never throws. */
export async function fetchApiState(signal: AbortSignal): Promise<ApiState> {
  try {
    const response = await fetch("/api/healthz", { signal });
    if (!response.ok) return "unavailable";
    const body = (await response.json()) as HealthResponse;
    return body.status === "ok" ? "ok" : "unavailable";
  } catch {
    return "unavailable";
  }
}
