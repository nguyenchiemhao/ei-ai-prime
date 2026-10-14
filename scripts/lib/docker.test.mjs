import test from "node:test";
import assert from "node:assert/strict";
import { ALL_PROFILE_ARGS, parseUpArgs, run, runWithTicks, upProfileArgs } from "./docker.mjs";

test("docker_up_profiles_default_to_core_and_model", () => {
  assert.deepEqual(upProfileArgs(), ["--profile", "core", "--profile", "model"]);
});

test("docker_up_profiles_follow_the_flags", () => {
  assert.deepEqual(upProfileArgs({ model: false }), ["--profile", "core"]);
  assert.deepEqual(upProfileArgs({ model: false, demo: true }), [
    "--profile",
    "core",
    "--profile",
    "demo",
  ]);
});

test("docker_all_profiles_cover_every_profile_of_the_compose_file", () => {
  assert.deepEqual(
    ALL_PROFILE_ARGS.filter((_, index) => index % 2 === 1),
    ["core", "model", "demo", "tools"],
  );
});

test("docker_parse_up_args_reads_known_flags_and_rejects_unknown_ones", () => {
  assert.deepEqual(parseUpArgs([]), { model: true, demo: false });
  assert.deepEqual(parseUpArgs(["--no-model", "--demo"]), { model: false, demo: true });
  assert.throws(() => parseUpArgs(["--fast"]), /unknown option --fast/);
});

test("docker_run_captures_output_and_returns_the_exit_code_without_a_shell", () => {
  const ok = run(process.execPath, ["-e", "console.log('a b'); process.exit(0)"], {
    capture: true,
  });
  assert.equal(ok.code, 0);
  assert.equal(ok.stdout.trim(), "a b");

  const failing = run(process.execPath, ["-e", "process.exit(4)"], { capture: true });
  assert.equal(failing.code, 4);

  assert.equal(run("definitely-not-a-command", [], { capture: true }).code, 127);
});

test("docker_run_with_ticks_calls_the_hint_while_the_command_runs_and_returns_its_exit_code", async () => {
  let ticks = 0;
  const code = await runWithTicks(
    process.execPath,
    ["-e", "setTimeout(() => process.exit(3), 350)"],
    {
      onTick: () => (ticks += 1),
      tickMs: 100,
    },
  );

  assert.equal(code, 3);
  assert.ok(ticks >= 2, `expected at least 2 ticks, got ${ticks}`);
});

test("docker_run_with_ticks_resolves_127_for_a_missing_command", async () => {
  const code = await runWithTicks("definitely-not-a-command", [], {
    onTick: () => {},
    tickMs: 1000,
  });

  assert.equal(code, 127);
});
