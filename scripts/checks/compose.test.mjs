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
  SIGNIN_DB_PASSWORD: "dummy-signin-pw",
  EI_AI_MASTER_KEY: "ab".repeat(32),
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
  for (const name of ["COMPOSE_PROJECT_NAME", "MODEL_CACHE_VOLUME", "ADMIN_PORT"]) delete env[name];
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
  assert.deepEqual(byProfile("model"), ["embedding", "model"]);
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

test("model_healthcheck_requires_the_checksummed_alias_in_v1_models", () => {
  const command = services.model.healthcheck.test.join(" ");
  const alias = services.model.environment.LLM_ALIAS;
  assert.match(alias, /^[a-z0-9.-]+$/);
  assert.ok(command.includes("/v1/models"), "must query /v1/models");
  assert.ok(
    !command.includes("/health"),
    "/health answers 200 without a loaded model (b11580 router mode)",
  );
  // Exact command (EA-24): the start script serves "<alias>@sha256-<12 hex>", so healthy means the
  // verified file is loaded. A weaker grep (for example "object":"list") would pass with no model.
  assert.deepEqual(services.model.healthcheck.test, [
    "CMD-SHELL",
    `curl -fsS http://localhost:8080/v1/models | grep -q '"id":"${alias}@sha256-'`,
  ]);
});

test("model_starts_through_the_checksum_script_with_a_file_pinned_at_a_commit", () => {
  const model = services.model;
  assert.equal(model.image, "ghcr.io/ggml-org/llama.cpp:server-b11580");
  assert.deepEqual(model.entrypoint, ["/bin/sh", "/opt/ei-ai/start-model.sh"]);
  assert.ok(!model.command, "the script builds the server command");
  const { LLM_MODEL_FILE: file, LLM_MODEL_URL: url, LLM_MODEL_SHA256: sha } = model.environment;
  assert.match(file, /^[^/]+\.gguf$/);
  assert.match(url, /^https:\/\/huggingface\.co\/.+\/resolve\/[0-9a-f]{40}\/.+\.gguf$/);
  assert.ok(url.endsWith(`/${file}`), "the URL and the file name must name the same file");
  assert.match(sha, /^[0-9a-f]{64}$/);
  const mounts = (model.volumes ?? []).map((v) => `${v.type} ${v.target} ${v.read_only === true}`);
  assert.deepEqual(mounts.sort(), ["bind /opt/ei-ai true", "volume /models false"]);
  const script = model.volumes.find((v) => v.target === "/opt/ei-ai");
  assert.equal(path.resolve(script.source), path.join(ROOT, "infra", "model"));
  assert.ok(fs.existsSync(path.join(ROOT, "infra", "model", "start-model.sh")));
});

test("model_sha256_and_alias_can_be_overridden", () => {
  const sha = "0".repeat(64);
  const moved = JSON.parse(config({ ...DUMMY, LLM_MODEL_SHA256: sha, LLM_ALIAS: "other" }).stdout);
  assert.equal(moved.services.model.environment.LLM_MODEL_SHA256, sha);
  assert.equal(moved.services.model.environment.LLM_ALIAS, "other");
  assert.match(moved.services.model.healthcheck.test[1], /"id":"other@sha256-'$/);
});

test("api_and_backend_tools_call_the_local_model_and_have_no_egress_proxy_yet", () => {
  for (const name of ["api", "backend-tools"]) {
    assert.equal(services[name].environment.MODEL_LOCAL_BASE_URL, "http://model:8080/v1");
    assert.equal(services[name].environment.EGRESS_PROXY_URL, undefined);
  }
});

test("embedding_healthcheck_requires_the_checksummed_alias", () => {
  const embedding = services.embedding;
  assert.equal(embedding.environment.LLM_ALIAS, "bge-m3");
  assert.deepEqual(embedding.healthcheck.test, [
    "CMD-SHELL",
    `curl -fsS http://localhost:8080/v1/models | grep -q '"id":"bge-m3@sha256-'`,
  ]);
  assert.equal(embedding.healthcheck.interval, "10s");
  assert.equal(embedding.healthcheck.timeout, "5s");
  assert.equal(Number(embedding.healthcheck.retries), 6);
  assert.equal(seconds(embedding.healthcheck.start_period), 600);
  assert.equal(Number(embedding.mem_limit), 2 * 1024 ** 3);
});

test("embedding_starts_through_the_checksum_script_with_a_file_pinned_at_a_commit", () => {
  const embedding = services.embedding;
  assert.equal(embedding.image, "ghcr.io/ggml-org/llama.cpp:server-b11580");
  assert.deepEqual(embedding.entrypoint, ["/bin/sh", "/opt/ei-ai/start-model.sh"]);
  assert.ok(!embedding.command, "the script builds the server command");
  const env = embedding.environment;
  assert.match(env.LLM_MODEL_FILE, /^[^/]+\.gguf$/);
  assert.match(
    env.LLM_MODEL_URL,
    /^https:\/\/huggingface\.co\/.+\/resolve\/[0-9a-f]{40}\/.+\.gguf$/,
  );
  assert.ok(env.LLM_MODEL_URL.endsWith(`/${env.LLM_MODEL_FILE}`));
  assert.match(env.LLM_MODEL_SHA256, /^[0-9a-f]{64}$/);
  assert.equal(env.LLM_SERVER_ARGS, "--embeddings --pooling cls -c 8192 -b 8192 -ub 8192 -t 6");
  const mounts = (embedding.volumes ?? []).map(
    (v) => `${v.type} ${v.target} ${v.read_only === true}`,
  );
  assert.deepEqual(mounts.sort(), ["bind /opt/ei-ai true", "volume /models false"]);
  const script = embedding.volumes.find((v) => v.target === "/opt/ei-ai");
  assert.equal(path.resolve(script.source), path.join(ROOT, "infra", "model"));
});

test("api_and_backend_tools_call_the_local_embedding_server", () => {
  for (const name of ["api", "backend-tools"])
    assert.equal(services[name].environment.MODEL_EMBEDDING_BASE_URL, "http://embedding:8080/v1");
});

test("api_and_backend_tools_get_the_platform_embedding_model", () => {
  for (const name of ["api", "backend-tools"])
    assert.equal(services[name].environment.EMBEDDING_MODEL_REF, "bge-m3@2026.10");
  const moved = JSON.parse(config({ ...DUMMY, EMBEDDING_MODEL_REF: "other@v2" }).stdout).services;
  for (const name of ["api", "backend-tools"])
    assert.equal(moved[name].environment.EMBEDDING_MODEL_REF, "other@v2");
});

test("api_and_backend_tools_get_the_rerank_setting_empty_by_default", () => {
  for (const name of ["api", "backend-tools"])
    assert.equal(services[name].environment.RERANK_MODEL_REF, "");
  const set = JSON.parse(
    config({ ...DUMMY, RERANK_MODEL_REF: "bge-reranker-v2-m3@2026.10" }).stdout,
  ).services;
  for (const name of ["api", "backend-tools"])
    assert.equal(set[name].environment.RERANK_MODEL_REF, "bge-reranker-v2-m3@2026.10");
});

test("api_gets_the_platform_chat_model", () => {
  assert.equal(services.api.environment.CHAT_MODEL_REF, "qwen3-4b-instruct-2507@2026.10");
  const moved = JSON.parse(config({ ...DUMMY, CHAT_MODEL_REF: "other@v2" }).stdout).services;
  assert.equal(moved.api.environment.CHAT_MODEL_REF, "other@v2");
});

test("embedding_pin_ignores_chat_overrides", () => {
  const sha = "0".repeat(64);
  const moved = JSON.parse(
    config({ ...DUMMY, LLM_MODEL_SHA256: sha, LLM_MODEL_FILE: "x.gguf", LLM_ALIAS: "other" })
      .stdout,
  ).services;
  assert.equal(moved.model.environment.LLM_MODEL_SHA256, sha);
  assert.deepEqual(moved.embedding.environment, services.embedding.environment);
  assert.deepEqual(moved.embedding.healthcheck, services.embedding.healthcheck);
});

test("embedding_pin_can_be_overridden_only_through_embedding_variables", () => {
  const sha = "1".repeat(64);
  const moved = JSON.parse(
    config({ ...DUMMY, EMBEDDING_MODEL_SHA256: sha, EMBEDDING_MODEL_ALIAS: "other" }).stdout,
  ).services;
  assert.equal(moved.embedding.environment.LLM_MODEL_SHA256, sha);
  assert.equal(moved.embedding.environment.LLM_ALIAS, "other");
  assert.match(moved.embedding.healthcheck.test[1], /"id":"other@sha256-'$/);
  assert.deepEqual(moved.model.environment, services.model.environment);
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
  for (const name of ["db", "valkey", "model", "embedding", "backend-tools", "migrate"])
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

test("only_api_and_backend_tools_get_the_sign_in_lookup_url", () => {
  // EA-22 (R42): the sign-in lookup role is the only cross-tenant read; never the migrate service.
  const holders = Object.entries(services)
    .filter(([, service]) =>
      Object.entries(service.environment ?? {}).some(
        ([name, value]) => name.startsWith("SIGNIN_") || String(value).includes("ei_ai_signin"),
      ),
    )
    .map(([name]) => name)
    .sort();
  assert.deepEqual(holders, ["api", "backend-tools", "db"]);
  // db only receives the password, to create the role in its first-start init script.
  assert.deepEqual(
    Object.keys(services.db.environment).filter((name) => name.startsWith("SIGNIN_")),
    ["SIGNIN_DB_PASSWORD"],
  );
  assert.equal(services.db.environment.SIGNIN_DB_PASSWORD, DUMMY.SIGNIN_DB_PASSWORD);
  for (const name of ["api", "backend-tools"]) {
    assert.equal(
      services[name].environment.SIGNIN_DATABASE_URL,
      `postgresql://ei_ai_signin:${DUMMY.SIGNIN_DB_PASSWORD}@db:5432/ei_ai`,
    );
  }
});

test("api_has_no_migrator_or_superuser_credentials", () => {
  const environment = JSON.stringify(services.api.environment);
  for (const forbidden of ["MIGRATION_", "ei_ai_migrator", "POSTGRES_PASSWORD", "postgres:"])
    assert.ok(!environment.includes(forbidden), `api environment contains ${forbidden}`);
});

test("api_restarts_after_it_is_killed", () => {
  // An OOM kill under its mem_limit must not leave the API down (EA-22).
  assert.equal(services.api.restart, "unless-stopped");
});

test("api_builds_set_password_links_for_the_local_admin", () => {
  assert.equal(services.api.environment.ADMIN_BASE_URL, "http://localhost:3000");
});

test("admin_port_moves_the_admin_host_port_and_the_link_base_together", () => {
  const moved = JSON.parse(config({ ...DUMMY, ADMIN_PORT: "3100" }).stdout).services;
  assert.deepEqual(
    moved.admin.ports.map((port) => `${port.host_ip}:${port.published}->${port.target}`),
    ["127.0.0.1:3100->8080"],
  );
  assert.equal(moved.api.environment.ADMIN_BASE_URL, "http://localhost:3100");
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

test("master_key_only_on_api_and_backend_tools", () => {
  for (const name of ["api", "backend-tools"]) {
    assert.equal(
      services[name].environment.EI_AI_MASTER_KEY,
      DUMMY.EI_AI_MASTER_KEY,
      `${name} must get the interpolated master key`,
    );
  }
  for (const name of ["db", "migrate", "valkey", "model", "embedding", "admin", "widget"]) {
    assert.ok(
      !("EI_AI_MASTER_KEY" in (services[name].environment ?? {})),
      `${name} must not get the master key`,
    );
  }
});
