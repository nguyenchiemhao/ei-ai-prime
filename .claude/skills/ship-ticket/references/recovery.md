# ship-ticket — recovery, escalation and the Blocked rule

Read this when an agent stops on an error or a usage limit, when a loop limit is hit, or when a ticket cannot move.

## Agent stopped on an API error

- Check the working tree and the dev log, then resume the **same** agent (`SendMessage`) with a short note of where it stopped.
- If the error names a reset time (e.g. "resets 12:40pm"), do not end the turn waiting for the owner: start a background Bash wait that exits about 2 minutes after the reset (`run_in_background`, a loop on `date` with short sleeps), and when it completes, resume the agent.
- Developers on large tickets append a dev-log checkpoint after every task, so a resume is exact.

## Escalate (any step)

Stop the pipeline, keep the working tree as is, and tell the owner: where it stopped, the last report file, the open findings, and 2–3 options (e.g. accept with known issues, give guidance and resume, split the ticket, abandon the branch). Resume from the step the owner chooses.

## Blocked rule

When a ticket cannot move because of something the team cannot decide or fix (an environment problem, a missing account or key, an owner decision with no safe default), transition it to *Blocked* and post the **Blocked comment** of `.claude/skills/jira-ticket-management/references/comment-templates.md` (a facts table and an owner-action table) with:

- **Reason** — what cannot proceed and which AC are affected;
- **Root cause** — verified now, with the command output or source;
- **Owner action needed** — numbered, concrete steps, and how to check they worked;
- **Impact** — which tickets wait on it;
- **Resume** — the command to run once it is fixed (e.g. `/ship-ticket EA-<n> --auto-commit`).
