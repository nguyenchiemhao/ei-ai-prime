// Downloads the Docker Compose release binary of MIN_COMPOSE_VERSION, verifies its sha256 and places it
// as a Docker CLI plugin. Used by the CI `stack` job (so CI runs the minimum supported version) and by
// developers who want to try that version:
//   node scripts/install-compose.mjs [--os linux|windows] [--arch x86_64|aarch64] [--dest <dir>] [--version x.y.z]
//   node scripts/install-compose.mjs --verify    fails unless `docker compose` is exactly that version (CI)
// Without --dest it installs into ~/.docker/cli-plugins, which overrides the Compose of Docker Desktop.
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { MIN_COMPOSE_VERSION, parseComposeVersion } from "./lib/compose-version.mjs";
import { compose } from "./lib/docker.mjs";

/** Release asset URLs of a Compose version for an os (linux|windows|darwin) and architecture. */
export function releaseUrls(version, platform = "linux", arch = "x86_64") {
  const file = `docker-compose-${platform}-${arch}${platform === "windows" ? ".exe" : ""}`;
  const base = `https://github.com/docker/compose/releases/download/v${version}/${file}`;
  return { binary: base, checksum: `${base}.sha256`, file };
}

/** The hex digest from the content of a `.sha256` release file ("<hex> *<name>"). */
export function parseSha256(text) {
  const match = text.trim().match(/^([0-9a-f]{64})\b/i);
  if (!match) throw new Error("the checksum file does not start with a sha256 digest");
  return match[1].toLowerCase();
}

/** Release architecture name for a Node process.arch value. */
export function composeArch(nodeArch = process.arch) {
  const arch = { x64: "x86_64", arm64: "aarch64" }[nodeArch];
  if (!arch) throw new Error(`no Docker Compose release binary for architecture ${nodeArch}`);
  return arch;
}

/** Throws unless the `docker compose version --short` output is exactly the expected version. */
export function verifyInstalled(output, expected) {
  const found = parseComposeVersion(output)?.join(".");
  if (found !== expected) {
    throw new Error(
      `docker compose is ${found ?? "not available"}, CI must run exactly ${expected}`,
    );
  }
}

async function download(url) {
  const response = await fetch(url, { redirect: "follow" });
  if (!response.ok) throw new Error(`download of ${url} failed: HTTP ${response.status}`);
  return Buffer.from(await response.arrayBuffer());
}

async function main(argv) {
  if (argv.includes("--verify")) {
    const result = compose(["version", "--short"], { capture: true });
    verifyInstalled(result.stdout, MIN_COMPOSE_VERSION);
    console.log(`docker compose ${MIN_COMPOSE_VERSION} verified`);
    return;
  }
  const option = (name, fallback) =>
    argv.includes(name) ? argv[argv.indexOf(name) + 1] : fallback;
  const platform = option("--os", process.platform === "win32" ? "windows" : process.platform);
  const version = option("--version", MIN_COMPOSE_VERSION);
  const destination = option("--dest", path.join(os.homedir(), ".docker", "cli-plugins"));
  const { binary, checksum, file } = releaseUrls(
    version,
    platform,
    option("--arch", composeArch()),
  );

  const [content, digestText] = await Promise.all([
    download(binary),
    download(checksum).then(String),
  ]);
  const actual = createHash("sha256").update(content).digest("hex");
  if (actual !== parseSha256(digestText))
    throw new Error(`sha256 mismatch for ${file}; nothing was installed`);

  fs.mkdirSync(destination, { recursive: true });
  const target = path.join(
    destination,
    platform === "windows" ? "docker-compose.exe" : "docker-compose",
  );
  fs.writeFileSync(target, content, { mode: 0o755 });
  console.log(`installed Docker Compose ${version} (${file}, sha256 verified) at ${target}`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}
