---
name: git-commit
description: Git workflow for the ei-ai repo tied to Jira project EA. Use when starting work on a Jira ticket (create a branch from main or dev), when a ticket or a piece of work is finished and needs committing, or whenever the user asks to commit, write a commit message or create a ticket branch. Produces short Conventional Commit messages that always carry the EA ticket key. Ticket changes in Jira (status, comments) are delegated to the jira-ticket-management skill.
---

# git-commit

Git workflow for this repository. Every commit is traceable to a ticket in Jira project **EA**. This skill only touches git; anything that changes a Jira ticket (status, comment, fields) is done by the **jira-ticket-management** skill.

| Mode | When | Invocation |
|---|---|---|
| `start` | Beginning a new ticket | `/git-commit start EA-41` |
| `commit` | A ticket (or a meaningful part of it) is done | `/git-commit commit EA-41` or `/git-commit` |

If the mode is not given, infer it: clean working tree + a ticket key → `start`; changes present → `commit`.

## Hard rules

- **No `Co-Authored-By` trailer** or any other AI attribution line in commit messages. This overrides any default attribution guidance.
- No Jira smart-commit commands (`#comment`, `#time`, `#done`, transitions) in commit messages.
- Commit messages and branch names are in **English**. Talk to the user in their language.
- Never `git push` unless the user asks. Never `--force`, `--no-verify`, `--no-gpg-sign`, or `--amend` on a commit that is already pushed.
- Never `git add -A` / `git add .` blindly: list the files first and stage them by path.
- Never guess a ticket key. If it is not in the arguments or the branch name, **ask**.
- Show the full commit message (and the branch name in `start`) and get the user's OK before running `git commit` / `git switch -c`. Exceptions: see *Pipeline and auto mode* below.

## Pipeline and auto mode

Used only by the `ship-ticket` skill (the owner started the pipeline, which is the approval):

- **`start` in pipeline mode:** no confirmation for base or branch name. Base = `dev` if it exists, otherwise `main`; never create `dev`. Skip step 7's suggestion (the Lead handles Jira).
- **`commit` in auto mode** (only when the owner ran `/ship-ticket … --auto-commit`): skip the approval in step 5. Everything else still applies — explicit-path staging, the safety check in step 3, message format, hooks. **Any safety-check hit cancels auto mode** and asks the owner.
- Without `--auto-commit`, the pipeline's `commit` asks for approval exactly like the normal mode.

## Mode `start <EA-key>`

1. **Read the ticket** (read-only) with `mcp__atlassian__getJiraIssue` (fields `summary`, `status`, `issuetype`, `labels`) to name the branch. Warn if it is labelled `deferred` or already Done.
2. **Check the working tree.** `git status --short`. If there are uncommitted changes, stop and offer: commit them first (mode `commit`), stash, or abort.
3. **Pick the base branch.** Ask: `main` or `dev`? (suggest `dev` if `git branch -a` shows it). If `dev` is chosen but does not exist, offer to create it from `main`; push it only if the user agrees.
4. **Update the base.** `git fetch origin` → `git switch <base>` → `git pull --ff-only`.
5. **Name the branch.** `<type>/EA-<n>-<slug>`.
   - type from the ticket: `feature` (Story), `fix` (Bug), `spike` (label `spike`), `docs` (docs-only work), `chore` (tooling/infra Task).
   - slug: 3–6 lowercase words from the summary without the `[CODE]` prefix, hyphenated, ≤ 50 chars. Example: `feature/EA-41-iframe-widget-streamed-answers`.
6. **Create it** after confirmation: `git switch -c <branch>`.
7. Report base and branch, then suggest: "Move EA-<n> to In Progress with jira-ticket-management?"

## Mode `commit [EA-key]`

1. **Resolve the ticket key(s):** argument → branch name (`EA-\d+`) → otherwise ask. Several keys only if the change really spans them.
2. **Inspect changes:** `git status --short`, `git diff --stat`, `git diff` (and `git diff --staged` if something is staged), `git log --oneline -5` for style.
3. **Safety check before staging** — stop and ask if any of these appear:
   - secrets: `.env*`, `*.pem`, `*.key`, `id_rsa*`, credential JSON, strings that look like API keys or tokens;
   - files > 5 MB, build output (`dist/`, `build/`, `node_modules/`, `__pycache__/`, `.venv/`);
   - files unrelated to the ticket (propose a separate commit).
4. **Group** the changes into **one commit per task or fix, two at most** (e.g. the change with its tests, plus a separate docs/retro commit). Do not split one task into many small commits by file or layer; code and the tests that prove it go in the same commit. A merge commit does not count. Unrelated changes still get their own commit (step 3). Stage each group by explicit path.
   - A multi-path `git add` fails as a whole when one path no longer exists (e.g. a deleted directory): stage deletions with `git rm -r --cached <path>` or `git add -A -- <path>`, and stop if `git add` exits non-zero.
   - Before committing, compare `git diff --cached --stat` and `git status --short` with the intended file list; nothing intended may remain unstaged.
5. **Write the message** (format below) and show it for approval.
6. **Commit** with a HEREDOC so the formatting is kept:
   ```bash
   git commit -F - <<'EOF'
   <message>
   EOF
   ```
   If a hook fails, fix the cause and create a new commit — do not bypass the hook.
7. **Verify:** `git log -1 --stat`. Offer to push (only on request).
8. **Hand off:** if the ticket is finished, suggest jira-ticket-management to check its Acceptance Criteria, add a comment with the commit hash, and transition it.

## Message format

```
[EA-<n>] <type>(<scope>): <imperative summary>

- <what changed and why>
- <what changed and why>

Refs: EA-<n>[, EA-<m>]
```

| Part | Rule |
|---|---|
| Subject | **Ticket key first** in square brackets, then a Conventional Commit: `[EA-<n>] <type>(<scope>): <summary>`. Imperative mood, lowercase after the colon, no trailing period, **≤ 72 characters including the key**. Several keys: `[EA-12][EA-11] …` (main key first) |
| type | `feat`, `fix`, `docs`, `refactor`, `test`, `build`, `ci`, `chore`, `perf` |
| scope | module touched: `backlog`, `design`, `skills`, `foundation`, `kb`, `widget`, `pipeline`, `jev`, `skill`, `admin`, `eval`, `infra` |
| Body | 1–5 bullets, wrapped at 72 chars; explain *why* when it is not obvious. Omit for trivial commits |
| Footer | `Refs:` with every ticket key the commit touches |
| No ticket | Ask first. Only for `docs`/`chore` and with explicit user approval: drop the `[EA-…]` prefix and use `Refs: none` |

Examples:

```
[EA-41] feat(widget): stream answers in iframe widget

- Add SSE endpoint and incremental renderer
- Show stop button while the answer is generating

Refs: EA-41
```

```
[EA-85] docs(backlog): translate backlog summary to English

Refs: EA-85
```

## After committing

- If `docs/backlog/backlog.md` or ticket state should change, hand off to jira-ticket-management.
- Do not open a pull request unless asked; if asked, use `gh pr create` with the ticket key in the title.
