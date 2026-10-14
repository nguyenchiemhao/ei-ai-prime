// Repository-level tasks that need a container: workflow lint and the full-history secret scan.
import { ROOT, docker } from "./docker.mjs";
import { scanHistory } from "./gitleaks.mjs";

export const ACTIONLINT_IMAGE = "rhysd/actionlint:1.7.12";

/** actionlint over .github/workflows; returns the exit code (0 = clean). */
export function actionlint() {
  return docker(
    [
      "run",
      "--rm",
      "--mount",
      `type=bind,source=${ROOT},target=/repo,readonly`,
      "--workdir",
      "/repo",
      ACTIONLINT_IMAGE,
      "-color",
    ],
    {},
  ).code;
}

/** gitleaks over the whole git history; returns the exit code (0 = no leaks). */
export function secretScan() {
  return scanHistory(ROOT, {}).code;
}
