import test from "node:test";
import assert from "node:assert/strict";
import { composeArch, parseSha256, releaseUrls, verifyInstalled } from "./install-compose.mjs";

test("install_compose_builds_the_release_urls", () => {
  assert.deepEqual(releaseUrls("2.17.3", "linux", "x86_64"), {
    binary:
      "https://github.com/docker/compose/releases/download/v2.17.3/docker-compose-linux-x86_64",
    checksum:
      "https://github.com/docker/compose/releases/download/v2.17.3/docker-compose-linux-x86_64.sha256",
    file: "docker-compose-linux-x86_64",
  });
  assert.equal(releaseUrls("2.17.3", "windows").file, "docker-compose-windows-x86_64.exe");
});

test("install_compose_reads_the_digest_from_a_release_checksum_file", () => {
  const digest = "6abb771a438b8ef82b0ff0ef0e2e404032699104c3c40c59cd174b56214876c3";
  assert.equal(parseSha256(`${digest} *docker-compose-linux-x86_64\n`), digest);
  assert.throws(() => parseSha256("<html>not found</html>"), /sha256/);
});

test("install_compose_picks_the_architecture_of_the_machine", () => {
  assert.equal(composeArch("x64"), "x86_64");
  assert.equal(composeArch("arm64"), "aarch64");
  assert.throws(() => composeArch("ia32"), /ia32/);
});

test("install_compose_verify_accepts_only_the_exact_version", () => {
  assert.doesNotThrow(() => verifyInstalled("2.20.3\n", "2.20.3"));
  assert.doesNotThrow(() => verifyInstalled("v2.20.3", "2.20.3"));
  assert.throws(() => verifyInstalled("5.6.0", "2.20.3"), /5\.6\.0.*2\.20\.3/);
  assert.throws(() => verifyInstalled("", "2.20.3"), /2\.20\.3/);
});
