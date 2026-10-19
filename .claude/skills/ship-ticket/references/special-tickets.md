# ship-ticket — Lead-run steps and design tickets

Read this when the plan marks a step **Lead-run**, or the profile is `design`.

## Lead-run steps

Subagents cannot launch other agents. A step the plan marks **Lead-run** (e.g. an independent second labeller or reviewer that must not share the developer's context) is done by you between developer phases:

1. Run the plan's leak check first; it must pass.
2. Copy only the allowed inputs into an isolated scratch folder.
3. Run a fresh agent on a different model than the developer.
4. Copy its output back and hand it to the developer.

## Design tickets on the claude.ai canvas (profile `design`)

No developer/reviewer subagents — subagents cannot write to claude.ai artifacts. You edit and publish the canvas yourself, publish early so the owner sees progress, and mirror the files to `docs/design/canvas/` in the same commit. QA is SKIPPED.
