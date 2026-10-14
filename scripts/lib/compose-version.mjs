// Minimum Docker Compose version for the local environment. One place; the CI `stack` job installs
/// exactly this version and the README names it. compose.yaml avoids features newer than this.
// Why 2.20.3 and not the 2.17 of the ADR: Compose 2.17.3-2.20.2 cannot build images against Docker
// Engine 29 ("listing workers for Build: ... PROTOCOL_ERROR"); 2.20.3 is the oldest release that can
// (bisected on Docker Engine 29.8.2: 2.18.1, 2.19.1, 2.20.0-2.20.2 fail; 2.20.3, 2.22.0, 2.24.7, 2.29.7, 2.32.4 work).
export const MIN_COMPOSE_VERSION = "2.20.3";

/** [major, minor, patch] from `docker compose version` text ("v2.17.3-desktop.1"), or null. */
export function parseComposeVersion(text) {
  const match = String(text).match(/(\d+)\.(\d+)\.(\d+)/);
  return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : null;
}

export function isAtLeast(version, minimum) {
  for (let index = 0; index < 3; index += 1) {
    if (version[index] !== minimum[index]) return version[index] > minimum[index];
  }
  return true;
}
