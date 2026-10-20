export type ApiResult<T> = { ok: true; data: T } | { ok: false; status: number; code: string };

const API_PREFIX = "/api";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

let csrfToken: string | null = null;

/** Forget the cached CSRF token; sign-in and sign-out rotate it, so the next unsafe call re-fetches. */
export function clearCsrfToken(): void {
  csrfToken = null;
}

async function readCode(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : "unknown";
  } catch {
    return "unknown";
  }
}

/** Body of a 2xx response; `undefined` when it is empty or not JSON (204, 202). */
async function readData<T>(response: Response): Promise<T> {
  try {
    return (await response.json()) as T;
  } catch {
    return undefined as T;
  }
}

async function ensureCsrfToken(): Promise<string | null> {
  if (csrfToken) return csrfToken;
  const response = await fetch(`${API_PREFIX}/auth/csrf`, { credentials: "same-origin" });
  if (!response.ok) return null;
  const body = (await response.json()) as { csrf_token?: unknown };
  csrfToken = typeof body.csrf_token === "string" ? body.csrf_token : null;
  return csrfToken;
}

/** JSON request to the same-origin API. Never throws: failures come back as `{ ok: false }`. */
export async function apiRequest<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<ApiResult<T>> {
  try {
    const headers: Record<string, string> = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (!SAFE_METHODS.has(method.toUpperCase())) {
      const token = await ensureCsrfToken();
      if (token) headers["X-CSRF-Token"] = token;
    }
    const response = await fetch(`${API_PREFIX}${path}`, {
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      return { ok: false, status: response.status, code: await readCode(response) };
    }
    return { ok: true, data: await readData<T>(response) };
  } catch {
    return { ok: false, status: 0, code: "network" };
  }
}
