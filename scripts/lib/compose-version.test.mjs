import test from "node:test";
import assert from "node:assert/strict";
import { MIN_COMPOSE_VERSION, isAtLeast, parseComposeVersion } from "./compose-version.mjs";

test("compose_version_parses_plain_prefixed_and_suffixed_strings", () => {
  assert.deepEqual(parseComposeVersion("2.17.3"), [2, 17, 3]);
  assert.deepEqual(parseComposeVersion("v2.17.3-desktop.1"), [2, 17, 3]);
  assert.deepEqual(parseComposeVersion("v5.6.0\n"), [5, 6, 0]);
  assert.deepEqual(parseComposeVersion("Docker Compose version v2.20.2"), [2, 20, 2]);
});

test("compose_version_rejects_text_without_a_version", () => {
  assert.equal(parseComposeVersion("nothing"), null);
  assert.equal(parseComposeVersion(""), null);
});

test("compose_version_is_at_least_compares_numerically_not_as_text", () => {
  assert.equal(isAtLeast([2, 17, 3], [2, 17, 3]), true);
  assert.equal(isAtLeast([2, 17, 2], [2, 17, 3]), false);
  assert.equal(isAtLeast([2, 9, 0], [2, 17, 3]), false);
  assert.equal(isAtLeast([2, 20, 0], [2, 17, 3]), true);
  assert.equal(isAtLeast([5, 6, 0], [2, 17, 3]), true);
  assert.equal(isAtLeast([1, 29, 2], [2, 17, 3]), false);
});

test("compose_version_minimum_is_a_parsable_triple", () => {
  assert.equal(parseComposeVersion(MIN_COMPOSE_VERSION)?.length, 3);
});
