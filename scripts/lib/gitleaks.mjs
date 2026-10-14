// Secret scanning with a pinned gitleaks image. The repository is mounted read-only; the exit code
// is 0 for "no leaks" and 1 for findings (the findings are redacted in the output).
import { randomInt } from "node:crypto";
import { ROOT, docker } from "./docker.mjs";

export const GITLEAKS_IMAGE = "ghcr.io/gitleaks/gitleaks:v8.30.1";

const base = (mounts) => [
  "run",
  "--rm",
  ...mounts.flatMap(([source, target]) => [
    "--mount",
    `type=bind,source=${source},target=${target},readonly`,
  ]),
  GITLEAKS_IMAGE,
];

const flags = (config) => ["--redact", "--no-banner", "--exit-code", "1", "--config", config];

/** Scans every commit of the repository (full history). */
export function scanHistory(repoRoot = ROOT, options = {}) {
  return docker(
    [...base([[repoRoot, "/repo"]]), "git", ...flags("/repo/.gitleaks.toml"), "/repo"],
    options,
  );
}

/** Scans the files of a directory (not git history) with the repository configuration. */
export function scanDir(directory, repoRoot = ROOT, options = {}) {
  return docker(
    [
      ...base([
        [repoRoot, "/repo"],
        [directory, "/scan"],
      ]),
      "dir",
      ...flags("/repo/.gitleaks.toml"),
      "/scan",
    ],
    options,
  );
}

/** A GitHub-token-shaped string built at run time, so no token-like literal exists in the repository. */
export function fakeGithubToken() {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  return `ghp_${Array.from({ length: 36 }, () => alphabet[randomInt(alphabet.length)]).join("")}`;
}
