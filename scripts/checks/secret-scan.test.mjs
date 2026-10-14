// EA-13 (SET-03) AC5: the scanner really fails on a secret. The full-history scan itself is the task
// repo:secret-scan (CI `checks` job and `npm run check`); it runs once, not again from here.
// Needs Docker (gitleaks runs from a pinned image). Run:  node --test scripts/checks/secret-scan.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { ROOT } from "../lib/docker.mjs";
import { fakeGithubToken, scanDir } from "../lib/gitleaks.mjs";

test("gitleaks_fails_on_generated_fake_token", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ei-ai-leak-"));
  fs.writeFileSync(path.join(dir, "settings.txt"), `github_token = "${fakeGithubToken()}"\n`);

  const result = scanDir(dir, process.env.GITLEAKS_REPO_ROOT || ROOT, { capture: true });

  assert.equal(
    result.code,
    1,
    `gitleaks must report the fake token (exit 1): ${result.stdout}${result.stderr}`,
  );
  assert.match(`${result.stdout}${result.stderr}`, /github-pat|leaks found/i);
});

test("gitleaks_passes_on_a_clean_directory", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ei-ai-clean-"));
  fs.writeFileSync(path.join(dir, "notes.txt"), "nothing secret here\n");

  const result = scanDir(dir, process.env.GITLEAKS_REPO_ROOT || ROOT, { capture: true });

  assert.equal(result.code, 0, `${result.stdout}${result.stderr}`);
});
