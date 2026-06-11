# Cairn Integrations

Factory AI's pitch is that its Droids ingest context from, and act through, the whole engineering
stack — GitHub, Jira/Linear, Sentry, Slack, CI. Cairn's answer is deliberately smaller and
git-native: **the `.cairn/` board + vault is the integration bus.** Anything that can read or write
committed files (a CI job, an MCP server, a cron line) plugs in without a platform.

**Honesty ledger** — what's tested vs template:

| Piece | Status |
|---|---|
| `github/cairn-run.yml`, `github/cairn-bot.yml` | **Templates.** Reviewed for the security model below; not exercised against a live repo. Dry-run on a fork first. |
| `#remember` hook (`hooks/cairn-remember-hook.sh`) | Ships with the plugin; same guarded-CLI path as the tested SessionEnd hook. |
| `cairn sync` (GitHub Issues, §2) | **Shipped + tested.** Every `gh` call in the suite is mocked (`tests/test_synccmd.py`); not exercised against a live repo — run the plan output past your eyes before `--apply`. |
| Linear/Jira / incident / cron recipes below | **Documented patterns**, not shipped code. They compose tested Cairn commands. |

## 1. GitHub Actions

Two copy-in workflow templates live in [`github/`](github/). Both need an `ANTHROPIC_API_KEY`
repository secret.

### `cairn-run.yml` — headless reconciler (Factory `droid exec` parity)

Copy to `.github/workflows/cairn-run.yml`. Trigger manually (workflow_dispatch, `base` input,
default `main`) or uncomment the cron block for scheduled runs. The job installs the Claude Code
CLI and runs `/cairn-run` headlessly with `--permission-mode acceptEdits`; the committed
`board.jsonl` is the work queue, so the run picks up whatever tickets are ready and stops when
none are.

Also enable: *Settings → Actions → General → "Allow GitHub Actions to create and approve pull
requests"* (the job opens its results PR with the built-in `GITHUB_TOKEN`).

**Security model**
- Maintainer-triggered only — never wire it to `pull_request`/`issue_comment` events.
- All GitHub context values reach `run:` scripts via `env:` indirection, never direct
  interpolation; the `base` input is additionally allowlist-validated.
- Results land on a `cairn/ci-run-<n>` branch behind a PR. The agent never pushes to base.
- A `concurrency` group serializes runs — the CI-surface mirror of `cairn run-lock`.
- Pin action refs to commit SHAs before production (comments mark where).

### `cairn-bot.yml` — `@cairn` PR comments (Factory `@droid` parity)

Copy to `.github/workflows/cairn-bot.yml`. Comment `@cairn review`, `@cairn security`, or
`@cairn rca` on any PR; the matching role runs against the PR diff (consulting a committed
`.cairn/vault/` if present) and replies as a PR comment.

**Security model**: only OWNER/MEMBER/COLLABORATOR comments trigger it; the comment body is
reduced to one allowlisted keyword and never touches a shell unquoted; the agent gets read-only
tools and the workflow has no `contents: write` — worst case for hostile diff text is a misleading
comment, not pushed code. Details in the file header.

## 2. Issue trackers — GitHub Issues (native) / Linear / Jira

### GitHub Issues — `cairn sync` (native, tested)

For GitHub the board doesn't need an MCP bridge: `cairn sync` speaks to GitHub Issues directly
through the `gh` CLI (`gh` must be installed and authenticated; without it the command fails
with `gh CLI required for sync`).

**Report-first, always.** Sync never silently mutates anything — the default output of both
directions is a JSON diff plan; only `--apply` executes it:

```bash
cairn sync push [--repo OWNER/NAME]            # plan: board -> issues (no gh needed to plan)
cairn sync push --apply                        # execute the plan via gh
cairn sync pull [--repo OWNER/NAME]            # plan: issues -> board (read-only gh)
```

What each direction plans:

- **push** — every board ticket with no issue mapping gets a *create issue* plan (title
  `[<TID>] <ticket spec title>`, label `cairn`, body = the ticket spec markdown plus the board
  fields); every mapped ticket that moved to `merged`/`cancelled` gets a *close issue* plan.
- **pull** — a `cairn`-labeled issue closed on GitHub while the board ticket is still live is
  **flagged, never auto-merged**: git truth beats issue state, so the plan tells you to run
  `cairn reconcile` and let the repo decide. A new `cairn`-labeled issue with no board ticket
  yields a *suggest board add* plan with a ready-to-run `cairn board add` command.

The ticket↔issue mapping lives in `.cairn/sync.json` (`{tid: issue_number}`), written atomically
through the same symlink-safe I/O as the board — board fields stay locked down.

**Security model**: `gh` is invoked with list-form argv only (never a shell), so titles and
bodies are single arguments that can't be parsed as options or shell text; a `--repo` value must
match plain `OWNER/NAME` (and may not start with `-`) before it reaches `gh`; pull is read-only
against GitHub and never writes the board.

### Linear / Jira — via MCP

Factory assigns a ticket to a Droid and gets a PR back. The local adaptation: **connect your
tracker's MCP server in Claude Code, and let the Cairn board mirror the tracker.**

1. Connect the MCP server once: `claude mcp add linear` (or your Jira MCP of choice).
2. Ticket assigned to you → start a session and plan from the ticket body:

   > Fetch LIN-482 from Linear (title, description, acceptance criteria), then run
   > `/cairn-plan` with that ticket body as the goal.

3. Mirror IDs so the trail is bidirectional — Cairn tickets carry a free-form `pr` field; point
   it at the tracker issue:

   ```bash
   cairn board set T1 pr=LIN-482
   ```

4. On merge, close the loop from the same session:

   > T1 is merged. Update LIN-482 in Linear: mark Done and comment with the merge commit
   > and a one-line summary from the vault decisions entry.

Jira is identical with a Jira MCP server and `pr=PROJ-123`. The board stays the source of truth
for *execution* state; the tracker stays the source of truth for *intent*.

## 3. Incident response — Sentry / PagerDuty

Factory's Reliability Droid flow is alert → triage → RCA → fix PR. Locally:

1. Connect the Sentry MCP server (`claude mcp add sentry`). PagerDuty pages should link back to
   the Sentry issue (or paste the stack trace directly — any artifact works).
2. Alert fires → open a session in the affected repo:

   > Fetch SENTRY-PROJ-129 (stack trace, breadcrumbs, first-seen release). Correlate with
   > `git log` since that release and with `.cairn/vault/issues.md` for known remedies.
   > Write the RCA — symptom, root cause, why it escaped, prevention — then:
   > `cairn vault append issues "<one-line RCA>"` and
   > `cairn board add '{"id":"T-fix-129","title":"<fix title>","status":"ready", ...}'`

3. The next `/cairn-run` (local or the CI workflow above) picks up the fix ticket. The RCA is
   permanent in the vault, so the *next* similar alert starts warm.

The `/cairn-rca` command packages this flow end-to-end (artifact -> signature -> correlation -> vault RCA -> fix ticket); the prompt above is the same flow spelled out for non-plugin surfaces.

## 4. Slack — explicit non-goal

Factory's Slack bot exists because its agent lives in a cloud runtime someone must reach
remotely. Cairn's agents live where your repo lives, so there is nothing to "message." The async
answers are:

- **Handoff packs** (`cairn handoff`, `/cairn-handoff`) — the portable "here's everything,
  continue anywhere" artifact you'd otherwise paste into a thread.
- **Headless CI** (§1) — "kick off work while away from the keyboard" is a workflow_dispatch
  button in the GitHub mobile app, with a PR as the reply.

## 5. Always-on / scheduled runs

The board is a durable queue, so "always-on" reduces to *run the reconciler on a timer*.

**crontab** (runs only when ready tickets exist — cheap no-op otherwise):

```cron
0 7 * * 1-5  cd /path/to/repo && /opt/homebrew/bin/claude -p "/cairn-run" --permission-mode acceptEdits >> /tmp/cairn-cron.log 2>&1
```

**launchd** (macOS-native; survives sleep better than cron): a `LaunchAgent` plist with
`ProgramArguments` of `["/bin/zsh","-lc","cd /path/to/repo && claude -p \"/cairn-run\""]` and a
`StartCalendarInterval` block, loaded via `launchctl load ~/Library/LaunchAgents/dev.cairn.run.plist`.

**CI schedule**: uncomment the `schedule:` cron block in `cairn-run.yml` for the
runs-even-when-your-laptop-is-closed variant.

All three are safe to stack: `cairn run-lock` (locally) and the workflow `concurrency` group
(in CI) guarantee two reconcilers never fight over the same ticket.

## 6. Inline memory capture — `#remember`

Not an external integration, but the same parity family (Factory's `#` capture / `/remember`).
With the plugin installed, any prompt starting with

```
#remember staging deploys read DATABASE_URL from doppler, not .env
```

is appended as a timestamped entry to `.cairn/vault/decisions.md` *before* the model sees it —
via the guarded CLI (`cairn vault append decisions …`), so the vault whitelist and symlink-safe
I/O apply. Implementation: `hooks/cairn-remember-hook.sh` (UserPromptSubmit). Prompts that don't
match pass through untouched; failures log to `/tmp/cairn-hook.log` and never block the prompt.
