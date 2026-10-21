// Local plumbing of the shared demo password: `npm run seed` hands EI_AI_SEED_PASSWORD to the CLI
// through the environment, never through argv (argv shows up in process lists and logs).
import { envFileValue } from "./ensure-env.mjs";

const NAME = "EI_AI_SEED_PASSWORD";

/** The password from `<root>/.env`, else the documented default in `<root>/.env.example`, else undefined. */
export const seedPassword = (root) =>
  envFileValue(root, NAME) ?? envFileValue(root, NAME, ".env.example");

/** `docker compose` arguments (without profiles): `-e NAME` forwards the value from the caller's environment. */
export const seedCommand = () => ["exec", "-T", "-e", NAME, "api", "ei-ai", "seed", "demo"];
