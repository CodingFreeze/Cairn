<div align="center">

```
   ██████╗ █████╗ ██╗██████╗ ███╗   ██╗
  ██╔════╝██╔══██╗██║██╔══██╗████╗  ██║
  ██║     ███████║██║██████╔╝██╔██╗ ██║
  ██║     ██╔══██║██║██╔══██╗██║╚██╗██║
  ╚██████╗██║  ██║██║██║  ██║██║ ╚████║
   ╚═════╝╚═╝  ╚═╝╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝
        durable waypoints for agents
```

**Coding agents are great at starting. Cairn makes them great at finishing.**

Multi-day, multi-session, multi-agent work — carried by the repo itself. A Claude Code plugin
(portable to Cursor & Codex) that turns `git` into the substrate agents continue work on,
instead of the place they dump it.

![tests](https://img.shields.io/badge/tests-537%20passing-brightgreen)
![python](https://img.shields.io/badge/python-3.9%2B%20·%20stdlib--only%20core-blue)
![plugin](https://img.shields.io/badge/Claude%20Code-plugin-8A2BE2)
![portable](https://img.shields.io/badge/portable-CC%20·%20Cursor%20·%20Codex-informational)
![security](https://img.shields.io/badge/hardened-dir--fd%20·%20openat%2Frenameat-critical)
![license](https://img.shields.io/badge/license-MIT-green)

</div>

---

> **A cairn** is a stack of trail-marker stones — durable waypoints that guide whoever comes next.
> That's the whole idea: your project's decisions, schema, fixes, and ticket state live as **plain
> files committed to git**, so any future session — in any tool — inherits the trail instead of
> starting cold.

## 🧭 Why Cairn?

Every agent demo is a cold start: greenfield repo, one heroic session, done. Real features take
**days** — sessions die, context compacts, you switch tools, a teammate takes over. Everything
you already have answers facts (*CLAUDE.md, memory tools remember what you decided*); nothing
answers **work-in-flight**: *which of the 16 tickets are merged, what's mid-rebase, which data
contract binds the next one?* Cairn answers that — deterministically, from disk:

| | personal memory tools | Cairn |
|---|---|---|
| Lives | your machine / your account | **the repo** |
| Remembers | facts about past chats | **the state of a half-done job** |
| Sharing | just you | **clone = inherit the brain** — a teammate's agent continues your feature |
| Resume | re-read notes, hope | **reconciled against git truth** (tested state machine, not vibes) |

Cairn was born from time spent working inside [Factory AI](https://factory.ai) — watching what
its droid orchestration gets right, and wanting that workflow on my own machine, in my own git
history, with no cloud runtime in the loop.

Factory AI's "Droids" showed the pattern: a coordinator decomposes work into tickets and dispatches
role-separated sub-agents (code / review / test), each with its own context window — so long jobs
don't degrade as one window fills. Its real moat is a **persistent cloud runtime** that keeps
filesystem and memory between sessions. Cairn replicates the orchestration **locally**, and
replaces the cloud runtime with something that's arguably better at solo/single-repo scale:

> **A git-committed vault beats process memory.** Process memory dies when a cloud machine spins
> down. A `.cairn/` vault is permanent, portable across tools, and survives session death — any new
> session rebuilds the entire run from disk.

You keep writing code. Cairn handles the coordination **and remembers everything**.

## 🐝 What Cairn does

```
  ┌─ /cairn-plan  (SPEC MODE) ──────────────────────────────────┐
  │  whole-project context → ticket DAG + schema/map +          │
  │  spec graph (Mermaid + interactive HTML) →                  │
  │  EDIT-OR-APPROVE + pick autonomy (manual/on-green/full)     │
  └──────────────────────────────┬──────────────────────────────┘
                                 v  (nothing runs until you approve)
  ┌─ /cairn-run  (judgment only — the mechanics are tested CLI) ────┐
  │                                                                 │
  │   cairn run-lock acquire ──► single-run token (no double runs)  │
  │       ▼                                                         │
  │   cairn step ──► atomic: pick ready ticket → worktree →         │
  │       │          record base_sha → board: dispatched →          │
  │       │          emit dispatch JSON  (rebase-on-base next)      │
  │       ▼                                                         │
  │   implementer (fresh ctx, worktree only) ──► returns summary    │
  │       │                                                         │
  │       ▼                                                         │
  │   reviewer + tester (+ security / semgrep gate) ─► PASS / FAIL  │
  │       │                                  │                      │
  │     PASS → fold summary into vault     FAIL → retry once        │
  │       │                                  │   else block         │
  │       ▼                                  ▼                      │
  │   cairn merge ──► atomic --no-ff merge → board: merged          │
  │   …loop… then cairn run-lock release                            │
  └─────────────────────────────────┬───────────────────────────────┘
                                    v
              session dies?  ──►  /cairn-resume
              rebuild actual(git) vs desired(board) from disk, continue
```

Misunderstandings surface at review (the same black-box tradeoff Factory has) — but **nothing is
ever trapped in a live session**. Kill the terminal mid-run; a new session reads the board + git and
picks up exactly where it left off.

## 🆕 v2 — what's new

- **Loop logic moved into the CLI** — each iteration is one tested command: `cairn step` (pick
  ready ticket → worktree → record `base_sha` → flip board → emit dispatch JSON), `cairn run-lock
  acquire/release` (single-run token), `cairn merge` (atomic integration). `/cairn-run` keeps
  only the judgment: dispatch, PASS/FAIL, vault folds.
- **Board format 2** (`.cairn/meta.json` `{"format": 2}`) — `base_sha` REQUIRED at dispatch +
  `dispatched_at` stamp feeding STALE notes in `cairn status`; a `cancelled` status that never
  satisfies readiness; `cairn board remove [--force]` with a dependent guard; natural-sort ids
  (`T2` < `T10`); branch charset validation.
- **Parallel work, serial merge** — `cairn ready --parallel` returns a `files_owned`-disjoint set
  of ready tickets; implementers run in parallel worktrees, integration stays serial.
- **Autonomy ladder + per-role models** — `manual` / `merge-on-green` / `full-auto` picked at the
  plan-approval gate; `.cairn/config.json` also routes models per role
  (`{"models": {"implementer": "sonnet", "reviewer": "opus", "tester": "haiku"}}`).
- **New surfaces** — `/cairn-rca` (failure artifact → vault RCA → fix ticket), `/cairn-readiness`
  (8-check agent-readiness score), and a `cairn-security` agent gating `security`-labeled tickets.
- **Specs + rules as artifacts** — approved specs persist as dated `.cairn/specs/YYYY-MM-DD-<slug>.md`;
  `.cairn/rules/*.md` + repo `AGENTS.md` are injected into every dispatch (`{{RULES}}`).
- **Memory upgrades** — ranked recall (`cairn recall --scope --limit`), `#remember` inline capture
  hook, and structured-summary capture as the primary vault path (heuristic harvest as fallback).
- **Integrations** — [`integrations/`](./integrations/): headless CI workflow, `@cairn` PR bot,
  Linear/Jira/Sentry MCP flows, cron/launchd recipes.

## 🚀 Quick Start

> **Install (Claude Code):** add this repo as a plugin marketplace (`.claude-plugin/marketplace.json`),
> then enable the `cairn` plugin. Outside Claude Code, just use the `bin/cairn` CLI directly.

### First five minutes — give your repo a brain

```bash
bin/cairn init                  # scaffold .cairn/ (auto-detects greenfield vs existing)
```
```text
/cairn-map                      # agent warms the vault: tooling, layout, conventions
#remember we use pnpm, never npm — broke CI twice    # ambient capture, any time
/cairn-recall pnpm              # ranked recall, any future session
/cairn-handoff                  # switching to Cursor mid-feature? it picks up warm
/cairn-resume                   # dead session / back after 2 weeks? rebuilt from disk
/cairn-readiness                # how agent-ready is this repo? scored, with fixes
```

Commit `.cairn/` — that's the point. Your teammate clones the repo and **their** agent inherits
every decision, convention, and half-finished plan. Memory tools remember *you*; the vault
travels with the *project*.

### Big feature? Engage the conductor

```text
/cairn-plan build a CSV importer with validation and tests
   -> ticket DAG + data contracts + spec graph -> edit-or-approve gate -> pick autonomy
/cairn-run                      # worktree-isolated agents, atomic merges, serial integration
/cairn-resume                   # continues exactly where ANY previous session stopped
```

The control plane is a tiny Python CLI with a **stdlib-only core** — zero dependencies as of v2
(future features may add *optional* extras, never a core requirement). It runs anywhere `python3`
does, and is more portable (and more reliable) than prose an LLM re-derives each turn:

```bash
bin/cairn board add '{"id": "T01"}'
bin/cairn board add '{"id": "T02", "depends_on": ["T01"]}'
bin/cairn next                       # -> T01  (lowest-id ready ticket, natural sort: T2 < T10)
bin/cairn board set T01 status=merged
bin/cairn next                       # -> T02
bin/cairn status                     # the board, as a table
```

## 🗂️ Spec mode — see the plan before it runs

Before a single ticket executes, `/cairn-plan` builds a **spec graph** of the whole project and
hands you an **edit-or-approve** gate — the part of Factory's planning phase worth keeping:

- **`.cairn/spec/graph.mmd`** — a Mermaid flow diagram (ticket nodes, dependency edges, status
  colors) that renders inline in GitHub / Cursor / VS Code / Claude.
- **`.cairn/spec/graph.html`** — a **self-contained, offline** interactive graph: layered DAG,
  pan/zoom, click a node to read its spec in a side drawer. No build step, no CDN — just open it.
- **`.cairn/spec/SPEC.md`** — the narrative: what unlocks what, where schema flows.

```bash
cairn spec --format both     # regenerate the graph from the current board any time
```

You review the graph, **edit the tickets / board / SPEC directly** (it's all files) and regenerate,
or approve — also picking the autonomy level (`manual` / `merge-on-green` / `full-auto`) at the same
gate. `/cairn-run` refuses to start until you do, and the approved spec persists as a dated
`.cairn/specs/` artifact. Factory edits in a GUI; you edit in git.

## 💾 The `.cairn/` vault — the moat

A single directory, committed to your repo. Any tool reads it; it never spins down.

```
.cairn/
  PROTOCOL.md     # the rules any agent follows (single-writer, reconcile-from-disk, rebase-before-turn)
  meta.json       # board format version stamp ({"format": 2}) — future migrations key off it
  config.json     # autonomy level (set at plan approval) + per-role model routing
  board.jsonl     # CONTROL PLANE — one line/ticket {id,status,branch,depends_on,base_sha,...}
  tickets/        # T01.md … declarative ticket specs
  specs/          # YYYY-MM-DD-<slug>.md — dated, approved spec artifacts
  rules/          # *.md coding rules injected (with AGENTS.md) into every dispatch
  vault/
    schema.md     # shared data contracts (carries ticket-6's schema → ticket-7)
    decisions.md  # append-only decision log
    issues.md     # known issues + remedies (fix-forward ledger, injected into dispatch)
    map.md        # repo warmth: where-things-live + a tooling/capability index
  handoff/
    latest.md     # portable resume pack (for a fresh session or a different tool)
  spec/
    graph.mmd     # Mermaid spec graph (renders in GitHub/Cursor/VS Code/Claude)
    graph.html    # self-contained interactive spec graph (pan/zoom + drawer)
    SPEC.md       # narrative system-flow + plan
```

## 🧩 The skill set

Cairn is one namespace, two layers. The **memory layer is usable standalone** — you don't have to
run the full loop to get durable, portable project memory.

<details>
<summary><b>Memory layer</b> — the moat (click to expand)</summary>

| Skill | Does | When to use |
|---|---|---|
| 💾 `cairn-vault` | init / maintain the durable vault in any repo | you want permanent project memory, with or without orchestration |
| 🗺️ `cairn-map` | build/refresh the repo-warmth + tooling index | onboarding a codebase; killing cold-start re-discovery |
| 🔎 `cairn-recall` | query the vault across sessions | "what did we decide about auth?" |
| 📦 `cairn-handoff` | emit a portable resume pack | moving to a fresh session / Cursor / Codex |
| 🔌 `cairn-adapter` | mirror into Serena / claude-mem **if present** | richer semantic recall on CC — never a hard dependency |
| 🧹 `cairn-dismiss` | session-end memory harvest (SessionEnd hook) | so a forgotten/closed session never loses its decisions |

</details>

<details>
<summary><b>Orchestration layer</b> — the flagship demo of the moat paying off</summary>

| Command / agent | Does |
|---|---|
| 🧠 `cairn-plan` | decompose a project into a ticket DAG; seed schema + map (where cross-ticket insight happens) |
| ⚡ `cairn-run` | the reconciler loop — worktree, rebase-before-turn, dispatch, gate, merge |
| ♻️ `cairn-resume` | reconcile-from-disk — rebuild a dead run from board + git |
| 📊 `cairn-status` / `cairn-report` | board print (with STALE notes) + human digest across tickets |
| 🚨 `cairn-rca` | failure artifact → root cause → vault RCA + fix ticket on the board |
| 🩺 `cairn-readiness` | 8-check agent-readiness score; offers to scaffold each missing artifact |
| 🤖 `cairn-implementer` | works **only** in its worktree, returns a structured summary |
| 🔬 `cairn-reviewer` / `cairn-tester` | fresh-eyes review vs acceptance + pass/fail tests |
| 🛡️ `cairn-security` | OWASP/secrets diff audit — gates `security`-labeled tickets |

</details>

## ⚙️ Three git-native mechanisms

The whole control plane is just git, used precisely:

| Mechanism | Problem it solves | How |
|---|---|---|
| **Single-writer + worktree isolation** | parallel agents racing the shared vault | agents write only their worktree; the orchestrator is the sole writer to board + vault. Git is the lock. |
| **Transactional board** | a dead session losing orchestration state | every transition is an atomic, fsync'd write to `board.jsonl`. Resume = reconcile from disk. |
| **Rebase-before-turn + issues injection** | a fix not reaching in-flight tickets | each ticket rebases on base before its turn; the issues-ledger is injected into every dispatch. Fix-forward, for free. |

## ⚔️ Factory parity

| Factory capability | Cairn's answer |
|---|---|
| Spec mode w/ approval gate + autonomy handoff | `/cairn-plan` fused gate: edit-or-approve **and** pick `manual` / `merge-on-green` / `full-auto` |
| Spec persistence as dated artifacts | `.cairn/specs/YYYY-MM-DD-<slug>.md` written at approval, committed to git |
| Per-role models (cheap worker / strong validator) | `.cairn/config.json` `{"models": {role: model}}` → per-Task `model:` routing |
| Graded autonomy levels | the autonomy ladder, enforced by `/cairn-run` at every merge |
| Headless `droid exec` in CI | `integrations/github/cairn-run.yml` — the committed board is the work queue |
| `@droid` PR-comment bot | `integrations/github/cairn-bot.yml` — `@cairn review` / `security` / `rca` |
| Reliability flow (alert → RCA → fix PR) | `/cairn-rca`: artifact → signature → vault RCA → fix ticket on the board |
| Org memory + `#` auto-capture | git vault + `#remember` hook + structured-summary fold (primary path) |
| Session search | `cairn recall --scope --limit` — ranked multi-term recall over the vault |
| Parallel droids / fleets | `cairn ready --parallel`: `files_owned`-disjoint parallel work, **serial merge** |
| Always-on / scheduled agents | cron / launchd / CI-schedule recipes; `run-lock` keeps reconcilers from fighting |
| Built-in security review | `cairn-security` agent gates `security`-labeled tickets (+ optional semgrep) |
| Readiness report | `/cairn-readiness` — 8-check score via `cairn readiness`, fixes offered |
| Agent-readable rules (`.factory/rules/`, AGENTS.md) | `.cairn/rules/*.md` + `AGENTS.md` injected into every dispatch (`{{RULES}}`) |

**Non-goals** — the cloud-only mechanics, each with its local answer: a **persistent cloud
runtime** (the git-committed vault + `/cairn-resume` rebuild any run from disk — it never spins
down); **multi-surface** Slack/web/desktop bots (handoff packs are the portable "continue
anywhere" artifact, and the headless CI button is the kick-off-while-away answer); **BYOK /
multi-provider** (Cairn rides Claude Code's models — handoff packs carry full state to Cursor
and Codex instead).

## 🏛️ Architecture

A **declarative reconciler over git**: desired state in `board.jsonl`, actual state in git
history, and `classify_ticket_state` reconciling the two (disambiguated by the `base_sha`
recorded at dispatch) — so a crash between "merged" and "board updated" recovers correctly, and
an untouched branch is never mistaken for finished work. The orchestrator is effectively
stateless; any session can drive it. Full state machine, concurrency model, and module map live
in [`ARCHITECTURE.md`](./ARCHITECTURE.md).

## 🛡️ Security model

Cairn's SessionEnd hook **auto-runs** in any repo containing a `.cairn/` — so a malicious repo is a
real threat. Cairn defends against it.

- **No path escapes.** Every `.cairn` read / write / mkdir / unlink / rename is **dir-fd anchored**
  (`openat`/`renameat` with `O_NOFOLLOW`) — a planted symlink (root, parent, or leaf) can't redirect
  I/O outside the repo, and the check-then-open TOCTOU window is closed.
- **No injection.** Ticket ids are charset-validated **on read** (`[A-Za-z0-9][A-Za-z0-9._-]*`, no
  `/`, `..`, leading `-`, or newline); `--base` must be an existing local branch; refs are passed
  with `--end-of-options`.
- **Fail closed.** Duplicate or malformed ids in a hand-edited `board.jsonl` are rejected, not
  silently collapsed.
- **No surprise writes.** Agents never write the board/vault; nothing auto-commits or pushes.

> Hardened across **14 rounds** of independent adversarial review (Codex), zero remaining Critical
> findings. The sole documented residual is exotic platforms lacking `os.supports_dir_fd` (macOS /
> Linux / BSD are unaffected).

## 🌐 Portability

The `.cairn/` core is plain markdown + JSONL + a stdlib CLI — it travels. In **Claude Code** the
`/cairn-*` commands + agents + hooks automate the loop. In **Cursor / Codex**, a human or agent
follows `.cairn/PROTOCOL.md` and runs the same `cairn` CLI. Same vault, same board, same guarantees.

## 🌱 Inspiration

Cairn started after I spent time with [**Factory AI**](https://factory.ai) and its autonomous
"Droids." The managed multi-agent orchestration genuinely clicked — ticket-first decomposition,
role-separated agents, spec-driven planning. Credit where it's due: Factory is a polished product
and worth a look if you want the hosted, enterprise version. What I wanted was the *pattern*,
running locally, that I owned — without the cloud runtime or the spin-down. Cairn is not a
Factory clone; it's the local, git-native distillation of what I found valuable.

## 📚 Docs

| Doc | For |
|---|---|
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | the thesis, `.cairn` layout, state machine, concurrency model, security model |
| [`docs/CASE-STUDY.md`](./docs/CASE-STUDY.md) | the dogfood story — 16 friction findings → 16 shipped fixes, the 16-ticket spec-graph test, continuation scars |
| [`ROADMAP.md`](./ROADMAP.md) | what's in flight, what's designed, what's exploratory — with honest status labels |
| [`INDEX.md`](./INDEX.md) | the full cairn-* skill/command/agent/module index |
| [`integrations/README.md`](./integrations/README.md) | CI, PR bot, tracker/incident MCP flows, cron recipes |
| `.cairn/PROTOCOL.md` | the rules any agent follows (written into each repo) |

## Tests

```bash
python -m pytest          # 537 tests
bash scripts/test.sh      # one-command runner, non-zero on failure
```

## License

[MIT](./LICENSE) — do what you want, no warranty.
