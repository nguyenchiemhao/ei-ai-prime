export type ApiResult<T> = { ok: true; data: T } | { ok: false; status: number; code: string };

const API_PREFIX = "/api";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

let csrfToken: string | null = null;
let pendingCsrfToken: Promise<string | null> | null = null;

/** Forget the cached CSRF token; sign-in and sign-out rotate it, so the next unsafe call re-fetches. */
export function clearCsrfToken(): void {
  csrfToken = null;
  pendingCsrfToken = null;
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

async function fetchCsrfToken(): Promise<string | null> {
  const response = await fetch(`${API_PREFIX}/auth/csrf`, { credentials: "same-origin" });
  if (!response.ok) return null;
  const body = (await response.json()) as { csrf_token?: unknown };
  return typeof body.csrf_token === "string" ? body.csrf_token : null;
}

/**
 * The cached token, or one shared request for it: every `GET /auth/csrf` sets a new cookie, so
 * concurrent unsafe calls (a batch of uploads) must not each fetch their own token.
 */
function ensureCsrfToken(): Promise<string | null> {
  if (csrfToken) return Promise.resolve(csrfToken);
  if (!pendingCsrfToken) {
    const request: Promise<string | null> = fetchCsrfToken().then(
      (token) => {
        // A token that arrives after clearCsrfToken() belongs to the old session: do not cache it.
        if (pendingCsrfToken === request) {
          csrfToken = token;
          pendingCsrfToken = null;
        }
        return token;
      },
      (error: unknown) => {
        if (pendingCsrfToken === request) pendingCsrfToken = null;
        throw error;
      },
    );
    pendingCsrfToken = request;
  }
  return pendingCsrfToken;
}

/** One same-origin request with the CSRF header on unsafe methods. Never throws. */
async function send<T>(
  method: string,
  path: string,
  headers: Record<string, string>,
  body: BodyInit | undefined,
): Promise<ApiResult<T>> {
  try {
    if (!SAFE_METHODS.has(method.toUpperCase())) {
      const token = await ensureCsrfToken();
      if (token) headers["X-CSRF-Token"] = token;
    }
    const response = await fetch(`${API_PREFIX}${path}`, {
      method,
      headers,
      credentials: "same-origin",
      body,
    });
    if (!response.ok) {
      return { ok: false, status: response.status, code: await readCode(response) };
    }
    return { ok: true, data: await readData<T>(response) };
  } catch {
    return { ok: false, status: 0, code: "network" };
  }
}

/** JSON request to the same-origin API. Never throws: failures come back as `{ ok: false }`. */
export function apiRequest<T>(method: string, path: string, body?: unknown): Promise<ApiResult<T>> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  return send<T>(method, path, headers, body === undefined ? undefined : JSON.stringify(body));
}

/** Raw-body POST (file upload) with the given headers and the same CSRF handling as `apiRequest`. */
export function apiUpload<T>(
  path: string,
  body: Blob,
  headers: Record<string, string>,
): Promise<ApiResult<T>> {
  return send<T>("POST", path, { ...headers }, body);
}

/**
 * POST JSON and hand the response body to `onChunk` as decoded text while it arrives (SSE).
 * Same CSRF header and error mapping as `apiRequest`; never throws. An abort comes back as
 * `{ ok: false, status: 0, code: "aborted" }`.
 */
export async function apiStream(
  path: string,
  body: unknown,
  onChunk: (text: string) => void,
  signal?: AbortSignal,
): Promise<ApiResult<void>> {
  try {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const token = await ensureCsrfToken();
    if (token) headers["X-CSRF-Token"] = token;
    const response = await fetch(`${API_PREFIX}${path}`, {
      method: "POST",
      headers,
      credentials: "same-origin",
      body: JSON.stringify(body),
      signal,
    });
    if (!response.ok) {
      return { ok: false, status: response.status, code: await readCode(response) };
    }
    if (response.body) {
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        const text = decoder.decode(value, { stream: true });
        if (text) onChunk(text);
      }
      const rest = decoder.decode();
      if (rest) onChunk(rest);
    }
    return { ok: true, data: undefined };
  } catch (error) {
    const aborted =
      signal?.aborted || (error instanceof DOMException && error.name === "AbortError");
    return { ok: false, status: 0, code: aborted ? "aborted" : "network" };
  }
}
