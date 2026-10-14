// EA-13 (SET-03) AC1, AC5: structure of compose.yaml, checked on the resolved configuration
// (`docker compose config --format json` with dummy credentials) and on the raw file.
// Needs Docker with Compose; a machine without Docker fails this check, it does not skip it.
// Run:  node --test scripts/checks/compose.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { ROOT, compose } from "../lib/docker.mjs";

const RAW = fs.readFileSync(path.join(ROOT, "compose.yaml"), "utf8");
const PROFILES = ["--profile", "core", "--profile", "model", "--profile", "tools"];
const DUMMY = {
  POSTGRES_PASSWORD: "dummy-postgres-pw",
  APP_DB_PASSWORD: "dummy-app-pw",
  MIGRATION_DB_PASSWORD: "dummy-migrator-pw",
};
// One-shot tool services: not started by "up", so no healthcheck.
const ONE_SHOT = ["backend-tools", "migrate"];

function envFile(values) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ei-ai-compose-"));
  const file = path.join(dir, "test.env");
  fs.writeFileSync(
    file,
    Object.entries(values)
      .map(([k, v]) => `${k}=${v}`)
      .join("\n") + "\n",
  );
  return file;
}

/** `docker compose config` with only the given variables (no .env, no inherited overrides). */
function config(values = DUMMY) {
  const env = { ...process.env };
  for (const name of ["COMPOSE_PROJECT_NAME", "MODEL_CACHE_VOLUME"]) delete env[name];
  return compose(["--env-file", envFile(values), ...PROFILES, "config", "--format", "json"], {
    capture: true,
    env,
  });
}

test("docker_compose_is_available", () => {
  const result = compose(["version", "--short"], { capture: true });
  assert.equal(
    result.code,
    0,
    `Docker Compose is required to check compose.yaml: ${result.stderr}`,
  );
});

const resolved = JSON.parse(config().stdout || "{}");
const services = resolved.services ?? {};
const byProfile = (profile) =>
  Object.keys(services)
    .filter((name) => services[name].profiles?.includes(profile))
    .sort();

test("compose_has_the_project_name_and_the_expected_services_per_profile", () => {
  assert.equal(resolved.name, "ei-ai");
  assert.deepEqual(byProfile("core"), ["admin", "api", "db", "valkey", "widget"]);
  assert.deepEqual(byProfile("model"), ["model"]);
  assert.deepEqual(byProfile("tools"), ["backend-tools", "migrate"]);
});

test("core_services_have_healthcheck_and_mem_limit", () => {
  for (const name of Object.keys(services)) {
    if (!ONE_SHOT.includes(name))
      assert.ok(services[name].healthcheck?.test, `${name}: no healthcheck`);
    // The test container (backend-tools) has never had a hard limit; migrate, a one-shot service, does.
    if (name !== "backend-tools")
      assert.ok(Number(services[name].mem_limit) > 0, `${name}: no mem_limit`);
  }
});

test("model_healthcheck_requires_alias_in_v1_models", () => {
  const command = services.model.healthcheck.test.join(" ");
  const alias = services.model.command[services.model.command.indexOf("--alias") + 1];
  assert.match(alias, /^[a-z0-9.-]+$/);
  assert.ok(command.includes("/v1/models"), "must query /v1/models");
  assert.ok(
    !command.includes("/health"),
    "/health answers 200 without a loaded model (b11580 router mode)",
  );
  assert.ok(command.includes(`"id":"${alias}"`), `must look for the alias ${alias}`);
  // Exact command: a weaker grep (for example one that only matches "object":"list") would report
  // healthy in router mode with no model loaded.
  assert.deepEqual(services.model.healthcheck.test, [
    "CMD-SHELL",
    `curl -fsS http://localhost:8080/v1/models | grep -q '"id":"${alias}"'`,
  ]);
});

test("model_command_pins_file_with_m_and_mu_at_a_commit", () => {
  const command = services.model.command;
  const file = command[command.indexOf("-m") + 1];
  const url = command[command.indexOf("-mu") + 1];
  assert.match(file, /^\/models\/.+\.gguf$/);
  assert.match(url, /^https:\/\/huggingface\.co\/.+\/resolve\/[0-9a-f]{40}\/.+\.gguf$/);
  assert.ok(url.endsWith(path.posix.basename(file)), "-m and -mu must name the same file");
  assert.equal(services.model.image, "ghcr.io/ggml-org/llama.cpp:server-b11580");
});

test("published_ports_are_fixed_and_loopback_only", () => {
  const published = Object.entries(services).flatMap(([name, service]) =>
    (service.ports ?? []).map((port) => ({
      name,
      host: port.host_ip,
      port: Number(port.published),
      target: Number(port.target),
    })),
  );
  assert.deepEqual(published.map(({ name, host, port }) => `${name} ${host}:${port}`).sort(), [
    "admin 127.0.0.1:3000",
    "api 127.0.0.1:8000",
    "widget 127.0.0.1:3001",
  ]);
  for (const name of ["db", "valkey", "model", "backend-tools", "migrate"])
    assert.equal(services[name].ports, undefined, `${name} must not publish a port`);
  assert.ok(
    !published.some(({ port }) => port === 4001 || port === 4002),
    "4001/4002 are reserved for the host demo (WGT-10)",
  );
});

test("passwords_come_from_required_env_vars", () => {
  const passwordLines = RAW.split("\n").filter(
    (line) => /PASSWORD/i.test(line) && !line.trim().startsWith("#"),
  );
  assert.ok(passwordLines.length >= 3, "expected the password variables in compose.yaml");
  for (const line of passwordLines)
    assert.match(line, /\$\{[A-Z_]+:\?[^}]+\}/, `literal or defaulted password: ${line.trim()}`);
  assert.equal(services.db.environment.POSTGRES_PASSWORD, DUMMY.POSTGRES_PASSWORD);
  assert.equal(services.db.environment.APP_DB_PASSWORD, DUMMY.APP_DB_PASSWORD);
  assert.ok(
    services.api.environment.DATABASE_URL.includes(
      `ei_ai_app:${DUMMY.APP_DB_PASSWORD}@db:5432/ei_ai`,
    ),
  );
});

test("only_migrate_and_backend_tools_get_the_migrator_credentials", () => {
  // AC5: the migration/owner role is used by the one-shot migrate service and the test container only.
  const holders = Object.entries(services)
    .filter(([, service]) =>
      Object.entries(service.environment ?? {}).some(
        ([name, value]) =>
          name.startsWith("MIGRATION_") || String(value).includes("ei_ai_migrator"),
      ),
    )
    .map(([name]) => name)
    .sort();
  assert.deepEqual(holders, ["backend-tools", "db", "migrate"]);
  // db only receives the password, to create the role in its first-start init script.
  assert.deepEqual(
    Object.keys(services.db.environment).filter((name) => name.startsWith("MIGRATION_")),
    ["MIGRATION_DB_PASSWORD"],
  );
  assert.ok(
    services.migrate.environment.MIGRATION_DATABASE_URL.includes(
      `ei_ai_migrator:${DUMMY.MIGRATION_DB_PASSWORD}@db:5432/ei_ai`,
    ),
  );
  assert.ok(
    services["backend-tools"].environment.MIGRATION_DATABASE_URL.includes(
      `ei_ai_migrator:${DUMMY.MIGRATION_DB_PASSWORD}@db:5432/ei_ai`,
    ),
  );
});

test("api_has_no_migrator_or_superuser_credentials", () => {
  const environment = JSON.stringify(services.api.environment);
  for (const forbidden of ["MIGRATION_", "ei_ai_migrator", "POSTGRES_PASSWORD", "postgres:"])
    assert.ok(!environment.includes(forbidden), `api environment contains ${forbidden}`);
});

test("migrate_runs_ei_ai_db_upgrade_from_the_runtime_image", () => {
  const migrate = services.migrate;
  assert.equal(migrate.build.target, "runtime");
  assert.deepEqual(migrate.command, ["ei-ai", "db", "upgrade"]);
  assert.equal(migrate.depends_on.db.condition, "service_healthy");
  assert.equal(migrate.environment.EI_AI_ENV, "local");
  assert.equal(migrate.ports, undefined);
});

test("compose_refuses_to_start_without_credentials", () => {
  const result = config({});
  assert.notEqual(result.code, 0);
  assert.match(result.stderr, /npm run up/);
});

test("api_connects_only_as_the_application_role_and_waits_for_its_dependencies", () => {
  const environment = services.api.environment;
  assert.equal(environment.EI_AI_ENV, "local");
  assert.ok(
    !environment.DATABASE_URL.includes("postgres:"),
    "the API must not connect as the superuser",
  );
  assert.equal(services.api.depends_on.db.condition, "service_healthy");
  assert.equal(services.api.depends_on.valkey.condition, "service_healthy");
  assert.equal(services["backend-tools"].environment.EI_AI_ENV, "test");
});

test("model_cache_volume_name_comes_from_model_cache_volume_with_a_default", () => {
  assert.equal(resolved.volumes["model-cache"].name, "ei-ai-model-cache");
  const overridden = config({ ...DUMMY, MODEL_CACHE_VOLUME: "my-cache" });
  assert.equal(JSON.parse(overridden.stdout).volumes["model-cache"].name, "my-cache");
});

test("compose_file_avoids_features_newer_than_the_minimum_compose_version", () => {
  const code = RAW.split("\n")
    .filter((line) => !line.trim().startsWith("#"))
    .join("\n");
  for (const feature of [/^include:/m, /^\s+develop:/m, /start_interval/, /--wait-timeout/]) {
    assert.doesNotMatch(code, feature, `newer Compose feature used: ${feature}`);
  }
});

/** Seconds in a Go-style duration as printed by `docker compose config` ("10m0s", "10s"). */
function seconds(duration) {
  const units = { h: 3600, m: 60, s: 1 };
  return [...String(duration).matchAll(/(\d+(?:\.\d+)?)([hms])/g)].reduce(
    (sum, [, amount, unit]) => sum + Number(amount) * units[unit],
    0,
  );
}

test("duration_parser_reads_compose_durations", () => {
  assert.equal(seconds("10m0s"), 600);
  assert.equal(seconds("10s"), 10);
  assert.equal(seconds("1h2m3s"), 3723);
});

test("a_model_that_never_loads_fails_the_wait_within_twelve_minutes", () => {
  const { start_period: start, interval, retries } = services.model.healthcheck;
  const worstCase = seconds(start) + seconds(interval) * Number(retries);
  assert.ok(
    worstCase <= 12 * 60,
    `npm run up could wait ${Math.round(worstCase / 60)} minutes for a broken model`,
  );
});
