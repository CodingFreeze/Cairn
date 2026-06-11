# Cairn — Skill Set Index

The `cairn-*` namespace is one Claude Code plugin = one growable skill SET. Two layers:
a **memory layer** (the moat — usable standalone) and an **orchestration layer** (the
flagship demo of that memory paying off). Below: every skill, command, and agent, what it
does in one line, and when to reach for it.

## Memory layer — skills (the durable, portable vault)

| Skill | Purpose | When to use |
|-------|---------|-------------|
| `cairn-vault` | Init/maintain the durable `.cairn/` vault in ANY repo. | First touch in a repo; you want session-death-proof memory even without orchestration. |
| `cairn-map` | Generate/refresh the repo-warmth + tooling map (`vault/map.md`). | Onboarding an existing codebase, or when "where does X live?" keeps coming up. |
| `cairn-recall` | Query the vault across sessions (enrichment engine first, grep fallback). | "What did we decide about auth?" — pulling prior decisions/schema/gotchas back into context. |
| `cairn-handoff` | Emit a portable resume pack to `handoff/latest.md`. | Switching tools (CC↔Cursor↔Codex) or ending a session you want a fresh session to resume cleanly. |
| `cairn-adapter` | Detect Serena/claude-mem; mirror vault writes + route recall; silent flat-file fallback. | Always-on enrichment when those engines exist; never a hard dependency. |
| `cairn-dismiss` | Session-end memory harvest of durable facts from the live conversation. | Wrapping up — capture decisions/gotchas/schema before the window dies. Hook-driven + `dismissed` keyword + `--cairn-dismissed`. |

## Orchestration layer — commands (drive the reconciler loop)

| Command | Purpose | When to use |
|---------|---------|-------------|
| `/cairn-plan` | **Spec mode**: decompose into a ticket DAG (auto-detects greenfield/existing), generate the spec graph, gate on edit-or-approve **+ pick the autonomy level** (→ `config.json`), persist the approved spec to `.cairn/specs/`. | Start of a multi-ticket feature; produces `tickets/*.md` + board + `spec/` graph, then waits for your approval. |
| `/cairn-run` | The reconciler loop — judgment only; mechanics are CLI (`run-lock acquire` → repeat `cairn step` → dispatch agents → `cairn merge` per autonomy → `run-lock release`). | Execute the approved DAG to completion in one driving session. |
| `/cairn-resume` | Reconcile actual(git) vs desired(board) and continue. | After a crash/closed terminal — the session-death-proof differentiator. |
| `/cairn-status` | Print the board (control plane) as a table, with STALE notes on >2h dispatched/in-progress tickets. | Any time you want to see ticket states + dependencies + branches. |
| `/cairn-report` | Human digest/changelog across tickets. | Reporting what happened across a run. |
| `/cairn-rca` | Failure artifact (log/trace/CI output) → signature → correlation with commits + vault issues → RCA in `vault/issues.md` + fix ticket on the board. | An incident or failing build needs a root cause and a tracked fix. |
| `/cairn-readiness` | Render the 8-check `cairn readiness` score; offer to scaffold each missing artifact (one approval per fix). | Before turning agents loose on a repo — "is this repo agent-ready?" |

## CLI utilities (the stdlib `cairn` control plane)

| Command | Purpose |
|---------|---------|
| `cairn init [--greenfield\|--existing] [--goal "…"]` | Scaffold `.cairn/` (auto-detects mode; writes the `meta.json` format-2 stamp; `--goal` seeds `vault/goal.md`). |
| `cairn board add\|get\|list\|set\|remove [--force]` · `cairn next` · `cairn status` | Read/write the board control plane (natural-sort ids; `remove` guards against live dependents; `status` flags STALE tickets). |
| `cairn step --base <b> --token <t>` | ONE atomic loop iteration: validate base → pick ready ticket → worktree → record `base_sha` → board→`dispatched` → emit dispatch JSON (or `done`/`blocked` + diagnosis). |
| `cairn run-lock acquire [--steal]` · `cairn run-lock release --token <t>` | Single-run token lock — two reconcilers never double-dispatch; stale (>2h) locks are steal-able. |
| `cairn ready [--parallel]` | List ready tickets; `--parallel` returns the `files_owned`-disjoint set safe to dispatch concurrently. |
| `cairn merge <id> --base <b>` | Atomic integration: commit → rebase → `--no-ff` merge → board=`merged` → worktree removed; FAIL touches nothing. |
| `cairn readiness` | The 8-check agent-readiness score as JSON (score + per-check ok/detail/fix). |
| `cairn spec [--format mermaid\|html\|both]` | (Re)generate the spec graph (`spec/graph.mmd` + interactive `spec/graph.html`) from the board. |
| `cairn vault append` · `cairn recall [--scope] [--limit]` · `cairn handoff` · `cairn dismiss` · `cairn harvest-candidates` | Memory-layer operations; recall is ranked multi-term search (hit count, recency tiebreak). |
| `cairn reconcile` · `cairn classify` | Desired-vs-actual git reconciliation (used by resume). |

## Orchestration layer — agents (role-separated, fresh context each)

| Agent | Purpose | When to use |
|-------|---------|-------------|
| `cairn-implementer` | Implement a ticket in its worktree; also update docs/vault for that ticket. | Dispatched by `/cairn-run` per ready ticket. Not invoked directly. |
| `cairn-reviewer` | Fresh-eyes diff review vs the ticket's acceptance criteria. | Dispatched after implementation; gates the merge. |
| `cairn-tester` | Run/write tests for the ticket; emit pass/fail. | Dispatched alongside review; the behavioral gate before merge. |
| `cairn-security` | Read-only OWASP/injection/secrets audit of the ticket diff; PASS/FAIL with file:line findings. | Dispatched when a ticket carries a `security` label (its FAIL is a FAIL); also the `@cairn security` PR-bot role. |

## The portable core — `.cairn/` (written into the target repo)

| File | Role |
|------|------|
| `PROTOCOL.md` | Rules any agent follows: single-writer, reconcile-from-disk, rebase-before-turn, issues-injection, no auto-commit. |
| `meta.json` | Board format version stamp (`{"format": 2}`) — future migrations key off it. |
| `config.json` | `autonomy` (manual / merge-on-green / full-auto, set at plan approval) + per-role `models` routing. |
| `board.jsonl` | Control plane — one line per ticket (`id/status/branch/pr/depends_on/owner/files_owned/base_sha/dispatched_at/updated`). |
| `run.lock` | Transient single-run token (`{token, ts}`) held by the live reconciler; stale after 2h. |
| `tickets/T##.md` | Declarative ticket specs (goal, acceptance, depends_on, files-owned). |
| `specs/YYYY-MM-DD-<slug>.md` | Dated, approved spec artifacts: narrative + build order + run policy + ticket links. |
| `rules/*.md` | Durable coding rules injected (with repo `AGENTS.md`) into every dispatch via `{{RULES}}`. |
| `vault/schema.md` | Shared data contracts; carries early-ticket schema forward. |
| `vault/decisions.md` | Append-only decision log (orchestrator sole writer). |
| `vault/issues.md` | Fix-forward ledger (problem/remedy/applies-to-future), injected into every dispatch. |
| `vault/map.md` | Repo warmth + tooling/capability index. |
| `handoff/latest.md` | Portable resume pack for cross-tool/cross-session pickup. |
| `spec/graph.mmd` | Mermaid spec graph (renders in GitHub/Cursor/VS Code/Claude). |
| `spec/graph.html` | Self-contained interactive spec graph (pan/zoom + click-to-drawer). |
| `spec/SPEC.md` | Narrative system-flow + plan, authored at plan time. |

## Integrations — `integrations/` (the board + vault as the integration bus)

| Piece | Purpose |
|------|---------|
| `integrations/README.md` | The full integration guide: what's tested vs template, security models, recipes. |
| `integrations/github/cairn-run.yml` | Headless reconciler workflow (Factory `droid exec` parity) — manual or cron-triggered CI runs off the committed board. |
| `integrations/github/cairn-bot.yml` | `@cairn review` / `security` / `rca` PR-comment bot (Factory `@droid` parity), read-only tools. |
| Linear / Jira flow | Tracker MCP server + `cairn board set T1 pr=LIN-482` mirroring — documented pattern. |
| Sentry / incident flow | Alert → `/cairn-rca` → vault RCA + fix ticket — documented pattern. |
| Cron / launchd / CI-schedule recipes | "Always-on" = run the reconciler on a timer; `run-lock` + CI `concurrency` keep runs serialized. |

## Hooks — `hooks/`

| Hook | Purpose |
|------|---------|
| `cairn-dismiss-hook.sh` (SessionEnd) | Session-end memory harvest — a closed session never loses its decisions. |
| `cairn-remember-hook.sh` (UserPromptSubmit) | `#remember <fact>` → timestamped `vault/decisions.md` entry via the guarded CLI. |

## CLI internals — `bin/cairn_core/`

`bin/cairn` is argument parsing only; the logic modules (`board` / `boardcheck` / `resolve` /
`runloop` / `mergeflow` / `reconcile` / `readiness` / `status` / `vaultio` / `dismisscmd` /
`safepath_fd` / spec-graph renderers / …) are mapped one-by-one in `ARCHITECTURE.md` → *Module
map*. Tests live in `tests/` (425 passing, `scripts/test.sh`).

See `ARCHITECTURE.md` for the memory-first thesis, state machine, concurrency model, and module map.
See `README.md` for install, v2 highlights, and the Factory-parity table.
See `integrations/README.md` for the CI / PR-bot / tracker / incident / cron recipes.

## Reference material

| Path | What |
|---|---|
| `examples/spec-graph/` | Rendered spec-graph HTML from the Driftwatch dogfood run (demo output) |
