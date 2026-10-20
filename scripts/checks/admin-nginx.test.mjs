// EA-22: every response of the admin nginx carries the anti-framing and referrer headers
// (clickjacking of the sign-in and set-password forms). nginx inherits `add_header` from the
// server block only into a location that has no `add_header` of its own, so a location that
// adds any header must repeat all of them. Run:  node --test scripts/checks/admin-nginx.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { ROOT } from "../lib/docker.mjs";

const CONF = path.join(ROOT, "apps/admin/nginx.conf");
const REQUIRED = [
  "X-Frame-Options DENY always",
  "Content-Security-Policy \"frame-ancestors 'none'\" always",
  "Referrer-Policy no-referrer always",
  "X-Content-Type-Options nosniff always",
];

/** The `add_header` values set directly in a block (not in its nested blocks). */
function ownHeaders(body) {
  let depth = 0;
  let flat = "";
  for (const char of body) {
    if (char === "{") depth += 1;
    if (depth === 0) flat += char;
    if (char === "}") depth -= 1;
  }
  return [...flat.matchAll(/^\s*add_header\s+([^;]+);/gm)].map((m) => m[1].trim());
}

/** The body of every `<keyword> ... { ... }` block, in order. */
function blocks(text, keyword) {
  const found = [];
  for (const match of text.matchAll(new RegExp(`(^|\\s)${keyword}\\b[^{;]*\\{`, "g"))) {
    let depth = 1;
    let index = match.index + match[0].length;
    const start = index;
    while (depth > 0 && index < text.length) {
      if (text[index] === "{") depth += 1;
      if (text[index] === "}") depth -= 1;
      index += 1;
    }
    found.push(text.slice(start, index - 1));
  }
  return found;
}

/** The headers each location actually sends: its own, or the server's when it has none. */
function headersPerLocation(text) {
  const [server] = blocks(text, "server");
  const inherited = ownHeaders(server);
  return blocks(server, "location").map((location) => {
    const own = ownHeaders(location);
    return own.length ? own : inherited;
  });
}

function missing(text) {
  const perLocation = headersPerLocation(text);
  assert.ok(perLocation.length > 0, "no location block found");
  return perLocation.flatMap((headers, index) =>
    REQUIRED.filter((header) => !headers.includes(header)).map((h) => `location ${index}: ${h}`),
  );
}

const SERVER_LEVEL = `server {
  ${REQUIRED.map((h) => `add_header ${h};`).join("\n  ")}
  location / { try_files $uri /index.html; }
}`;

test("headers_at_server_level_reach_every_location_without_its_own_add_header", () => {
  assert.deepEqual(missing(SERVER_LEVEL), []);
});

test("a_location_with_its_own_add_header_loses_the_server_headers", () => {
  const overridden = SERVER_LEVEL.replace(
    "location / {",
    'location / { add_header Cache-Control "no-cache";',
  );
  assert.equal(missing(overridden).length, REQUIRED.length);
});

test("every_admin_location_sends_the_security_headers", () => {
  assert.deepEqual(missing(fs.readFileSync(CONF, "utf8")), []);
});

test("no_full_content_security_policy_yet", () => {
  // Only frame-ancestors in this ticket; a script/style policy is a later, tested change.
  const csp = fs.readFileSync(CONF, "utf8").match(/Content-Security-Policy\s+"([^"]*)"/g) ?? [];
  for (const value of csp) assert.match(value, /"frame-ancestors 'none'"/);
});
