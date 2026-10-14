import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { runSmoke } from "./smoke.mjs";

function server(handler) {
  return new Promise((resolve) => {
    const instance = http.createServer(handler).listen(0, "127.0.0.1", () => {
      resolve({
        url: `http://127.0.0.1:${instance.address().port}`,
        close: () => instance.close(),
      });
    });
  });
}

const json = (response, status, body) => {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(body));
};

test("smoke_passes_when_every_probe_answers_200_with_the_expected_body", async () => {
  const fake = await server((request, response) => {
    if (request.url === "/" || request.url === "/index.html") return response.end("<html></html>");
    return json(response, 200, { status: "ok", checks: {} });
  });
  const lines = [];

  const ok = await runSmoke({ api: fake.url, admin: fake.url, widget: fake.url }, (line) =>
    lines.push(line),
  );
  fake.close();

  assert.equal(ok, true, lines.join("\n"));
  assert.equal(lines.length, 5);
  assert.ok(lines.every((line) => line.startsWith("PASS")));
});

test("smoke_fails_when_readyz_returns_503", async () => {
  const fake = await server((request, response) =>
    request.url === "/readyz"
      ? json(response, 503, { status: "unavailable" })
      : json(response, 200, { status: "ok" }),
  );
  const lines = [];

  const ok = await runSmoke({ api: fake.url, admin: fake.url, widget: fake.url }, (line) =>
    lines.push(line),
  );
  fake.close();

  assert.equal(ok, false);
  assert.ok(lines.some((line) => line.startsWith("FAIL api /readyz - HTTP 503")));
});

test("smoke_fails_when_the_body_status_is_not_ok_or_the_host_is_down", async () => {
  const fake = await server((request, response) => json(response, 200, { status: "degraded" }));
  const lines = [];

  const wrongBody = await runSmoke({ api: fake.url, admin: fake.url, widget: fake.url }, (line) =>
    lines.push(line),
  );
  fake.close();
  const down = await runSmoke(
    { api: "http://127.0.0.1:1", admin: "http://127.0.0.1:1", widget: "http://127.0.0.1:1" },
    (line) => lines.push(line),
  );

  assert.equal(wrongBody, false);
  assert.equal(down, false);
  assert.ok(lines.some((line) => line.includes("status is not ok")));
});
