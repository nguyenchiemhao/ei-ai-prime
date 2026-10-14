import test from "node:test";
import assert from "node:assert/strict";
import { memoryWarning, parseMemory, totalMemoryLimit } from "./memory-preflight.mjs";

const GIB = 1024 ** 3;
const services = {
  db: { mem_limit: GIB },
  valkey: { mem_limit: "268435456" },
  model: { mem_limit: "6g" },
  admin: { mem_limit: "64m" },
  nolimit: {},
};

test("memory_preflight_parses_bytes_and_unit_suffixes", () => {
  assert.equal(parseMemory(GIB), GIB);
  assert.equal(parseMemory("268435456"), 268435456);
  assert.equal(parseMemory("6g"), 6 * GIB);
  assert.equal(parseMemory("64m"), 64 * 1024 ** 2);
  assert.equal(parseMemory("512MB"), 512 * 1024 ** 2);
  assert.equal(parseMemory(undefined), 0);
});

test("memory_preflight_sums_the_limits_of_the_selected_services", () => {
  assert.equal(totalMemoryLimit(services), GIB + 268435456 + 6 * GIB + 64 * 1024 ** 2);
});

test("memory_preflight_warns_with_the_wslconfig_fix_when_limits_exceed_the_engine_memory", () => {
  const text = memoryWarning(services, 7.2 * GIB);

  assert.match(text, /but Docker has 7\.2 GB/);
  assert.match(text, /\.wslconfig/);
  assert.match(text, /memory=10GB/);
  assert.match(text, /wsl --shutdown/);
  assert.match(text, /--no-model/);
});

test("memory_preflight_is_silent_when_the_limits_fit_or_the_total_is_unknown", () => {
  assert.equal(memoryWarning(services, 16 * GIB), null);
  assert.equal(memoryWarning(services, 0), null);
  assert.equal(memoryWarning({}, 4 * GIB), null);
});
