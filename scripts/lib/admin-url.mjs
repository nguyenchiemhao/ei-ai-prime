// Base URL of the admin UI on the host. The admin host port is ADMIN_PORT (default 3000), resolved like
// Compose resolves ${ADMIN_PORT:-3000}: the shell environment first, then .env. ADMIN_URL overrides all.
import { envFileValue } from "./ensure-env.mjs";

export const DEFAULT_ADMIN_PORT = "3000";

/**
 * @param {string} root repository root (where .env lives)
 * @param {Record<string, string | undefined>} env usually process.env
 * @returns {string}
 */
export function adminUrl(root, env) {
  if (env.ADMIN_URL) return env.ADMIN_URL;
  // A shell value, even empty, shadows .env; empty then means the default (`${ADMIN_PORT:-3000}`).
  const port =
    (env.ADMIN_PORT !== undefined ? env.ADMIN_PORT : envFileValue(root, "ADMIN_PORT")) ||
    DEFAULT_ADMIN_PORT;
  return `http://localhost:${port}`;
}
