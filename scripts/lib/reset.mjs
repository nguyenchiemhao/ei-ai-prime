// `npm run reset`: stop the stack and delete its database volume, and only that one.
// The volume name is asked from Compose itself (project name from the shell, then .env, then the
// `name:` in compose.yaml), so an isolated project set in .env never deletes the main stack's data.
import { ALL_PROFILE_ARGS, ROOT, compose, docker } from "./docker.mjs";

/** Full name of the `db-data` volume as Compose resolves it for the project in `cwd`. */
export function dbVolumeName(cwd = ROOT, env = process.env) {
  const result = compose([...ALL_PROFILE_ARGS, "config", "--format", "json"], {
    capture: true,
    cwd,
    env,
  });
  if (result.code !== 0) throw new Error(`docker compose config failed: ${result.stderr.trim()}`);
  const name = JSON.parse(result.stdout).volumes?.["db-data"]?.name;
  if (!name) throw new Error("compose.yaml does not define the db-data volume");
  return name;
}

/** Returns { code, message }; `options.capture` keeps docker's own output quiet (tests). */
export function resetDatabase(cwd = ROOT, env = process.env, options = {}) {
  const volume = dbVolumeName(cwd, env);
  const stopped = compose([...ALL_PROFILE_ARGS, "down", "--remove-orphans"], {
    cwd,
    env,
    ...options,
  });
  if (stopped.code !== 0) return { code: stopped.code, message: "docker compose down failed" };
  if (docker(["volume", "inspect", volume], { capture: true }).code !== 0) {
    return { code: 0, message: `Nothing to reset: volume ${volume} does not exist.` };
  }
  const removed = docker(["volume", "rm", volume], { ...options });
  if (removed.code !== 0)
    return { code: removed.code, message: `Could not delete volume ${volume}.` };
  return {
    code: 0,
    message: `Deleted the database volume ${volume}. The model cache was not touched.`,
  };
}
