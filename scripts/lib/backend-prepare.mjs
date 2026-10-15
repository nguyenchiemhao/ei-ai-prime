// `npm run backend -- prepare`: pull the database and Valkey images and build the backend tools and
// migrate images, without running any test. CI runs it as its own step before the tenant-isolation
// suite, so that suite's 5-minute cap measures the suite and not a registry or a pip install.
import { ensureEnv } from "./ensure-env.mjs";
import { ROOT, compose } from "./docker.mjs";

/** Returns the exit code (0 = images ready). */
export function prepareBackendServices() {
  ensureEnv(ROOT); // compose interpolates ${VAR:?} for every service
  const pulled = compose(["--profile", "core", "pull", "db", "valkey"]);
  if (pulled.code !== 0) return pulled.code;
  return compose(["--profile", "tools", "build", "backend-tools", "migrate"]).code;
}
