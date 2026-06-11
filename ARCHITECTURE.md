# Cairn — Architecture

> A local, git-native replica of managed multi-agent orchestration — with **durable,
> portable memory** as the headline differentiator.

## The memory-first thesis

Managed orchestration tools sell four things: a coordinator that decomposes work into
tickets and dispatches role-separated subagents (each with its own context window); a warm
cloud runtime that keeps filesystem/credentials/process state between sessions; enterprise
ingest; and a ticket-first "one PR per ticket" workflow.

Single-agent tools instead hold plan + code + verification in **one context window** that
degrades on long multi-step work.

Cairn's wedge is **not** "another agent orchestrator." It is the part both managed
orchestration **and** generic agent-team plugins lack:

> **Session-death-proof, tool-portable, git-native durable memory + resumable orchestration.**

The durable memory is the moat. The orchestration loop is the flagship *demo* of that memory
paying off: cross-ticket schema reuse, fix-forward, and resume-after-crash. The memory skills
are useful **standalone**, even if you never run the full loop. A git-committed vault **beats**
a managed process memory on durability and portability — it never spins down, and it travels.

## The portable core — `.cairn/`

Everything Cairn knows lives in a plain directory committed into the target repo. Pure
markdown + JSONL. Any tool can read it.

```
.cairn/
  PROTOCOL.md        # rules ANY agent follows
  meta.json          # board format version ({"format": 2}) — migrations key off it
  config.json        # autonomy level + per-role model routing (set at plan approval)
  board.jsonl        # CONTROL PLANE — one line/ticket
  run.lock           # transient single-run token ({token, ts}) — see concurrency model
  tickets/T01.md     # declarative ticket specs
  specs/             # YYYY-MM-DD-<slug>.md — dated, approved spec artifacts
  rules/             # *.md rules injected (with AGENTS.md) into every dispatch
  vault/
    schema.md        # shared data contracts (carries ticket-6 -> ticket-7)
    decisions.md     # append-only decision log
    issues.md        # fix-forward ledger (injected into every dispatch)
    map.md           # repo warmth + tooling/capability index
  handoff/latest.md  # portable resume pack
```

## The ticket state machine (board format 2)

```
todo ──► dispatched ──► in-progress ──► pr-open ──► merged
              │               │             │
              └───────────────┴─────────────┴──► blocked
any non-merged ─────────────────────────────────► cancelled
```

- `todo → dispatched` happens only inside `cairn step`, which **requires** recording the
  base tip as `base_sha` and stamps `dispatched_at` on the same transition. `base_sha` is what
  lets `classify_ticket_state` distinguish an untouched branch from finished (FF-merged) work;
  `dispatched_at` feeds staleness detection — `cairn status` flags dispatched/in-progress
  tickets older than 2h as STALE.
- `blocked` is the retry-exhausted / conflict / failed-gate parking state; the operator (or a
  fix ticket) unblocks it.
- `cancelled` **never satisfies readiness**: a dependent of a cancelled ticket stays blocked
  until the operator removes the edge, cancels it too, or forces removal — treating cancelled
  like merged would unblock work whose input never landed. `cairn board remove` refuses to
  delete a ticket with live dependents unless `--force`.
- Ids natural-sort (`T2` before `T10`) and are charset-validated on read; branch names are
  charset-validated too.
- `.cairn/meta.json` carries `{"format": 2}` (`board.FORMAT_VERSION = 2`); future board
  migrations key off it.

## Three git-native mechanisms

Cairn stops storing orchestration state in the live context. **Git is the authority** and the
**orchestrator is a stateless reconciler** over a declarative board. Three mechanisms, all
pure git:

1. **Single-writer + worktree isolation — the lock, without a lock.**
   Implementer subagents write ONLY their own git worktree (code) plus a return summary. The
   orchestrator (the live `cairn-run` session) is the SOLE writer to `board.jsonl` and
   `vault/`. Worktrees isolate parallel code. Two writers never touch the board — git is the
   lock. (Two *orchestrators* are excluded by the run lock — see the concurrency model below.)

2. **Transactional board writes — crash-safe; resume = reconcile from disk.**
   Every board mutation is an atomic temp-file + rename, so a crash never leaves a
   half-written `board.jsonl`. Because all orchestration state lives in the board, a brand-new
   session rebuilds actual-vs-desired from the board + git. **Session death is a non-event.**

3. **Rebase-before-turn + issues-ledger injection — fix-forward, for free.**
   Each ticket branch rebases on the integration target immediately before its turn, so it
   inherits every previously merged fix via git. Every dispatch prompt also injects
   `vault/issues.md` remedies, so a fix discovered mid-run reaches still-pending tickets both
   through git history and through the prompt.

## The reconciler loop — mechanics in the CLI, judgment in the prompt

v2's core change: the loop's *mechanics* moved out of prose into tested CLI commands
(`runloop.py`). A prose state machine is only as strong as LLM context fidelity; a CLI command
is deterministic and covered by tests. `/cairn-run` retains only judgment — dispatching agents,
deciding PASS/FAIL, folding memory into the vault, and talking to the operator.

```
TOKEN = cairn run-lock acquire                 # single-run token; refuse if a run is live
loop:
  cairn step --base $BASE --token $TOKEN       # ONE atomic, tested command:
      # validate base -> pick next ready ticket -> create/reuse worktree on cairn/<TID>
      # -> record base_sha -> board: todo->dispatched (+dispatched_at) -> emit dispatch JSON
      # terminal outputs: {"action":"done"} | {"action":"blocked", cycle/missing_deps...}
  git rebase $BASE in the worktree             # rebase-before-turn: inherits ALL prior fixes
  dispatch cairn-implementer (model per config.json) with:
      ticket spec + vault/schema.md + vault/issues.md + tooling index
      + {{RULES}} (.cairn/rules/*.md + AGENTS.md)
  receive structured summary (SCHEMA_UPDATES / DECISIONS / ISSUES_FOUND)
  dispatch cairn-reviewer + cairn-tester
      (+ cairn-security if the ticket carries a `security` label; + semgrep if present)
  if PASS:
      fold the structured summary into the vault    # SOLE writer; PRIMARY memory path
      cairn merge $TID --base $BASE                  # atomic: commit -> rebase -> --no-ff
                                                     # merge -> board: merged -> worktree gone
      # per autonomy: manual pauses first; merge-on-green / full-auto do not
  else:
      retry ONCE with failure reasons injected
      still failing -> board: blocked; append remedy to issues.md; surface; continue
cairn run-lock release --token $TOKEN          # on EVERY exit path
```

The orchestrator is **not** an agent — it is the live `cairn-run` session driving the loop and
acting as sole vault/board writer. `cairn-resume` runs the same reconcile against git after a
crash, which is why a closed terminal loses nothing.

## Concurrency model — single writer + run lock

Two layers, two different races:

1. **Single writer** (agents vs orchestrator): agents never write board or vault; the
   orchestrator folds their returned summaries. Worktrees isolate code writes. This was v1's
   guarantee and is unchanged.
2. **Run lock** (orchestrator vs orchestrator): two concurrent `/cairn-run` sessions could both
   read the same "next ready" ticket before either flips the board — a same-ticket double
   dispatch. `flock`/pid schemes can't span the read-then-dispatch window across CLI
   invocations (each invocation is a new process; the orchestrator is an LLM session with no
   stable pid). Instead `.cairn/run.lock` holds `{token, ts}`: `run-lock acquire` mints the
   token, every `cairn step --token` verifies it and heartbeats `ts`, `run-lock release` frees
   it. A stale lock (>2h) or `--steal` replaces it — deterministic, testable, crash-survivable.
   In CI, the workflow `concurrency` group is the same guarantee on a different surface.

## Parallel work, serial merge

`cairn ready --parallel` (`ready_all` + `parallel_safe`) returns a prefix-greedy set of ready
tickets whose `files_owned` are pairwise disjoint (directory-prefix overlap counts; an empty
`files_owned` is a wildcard and always runs alone). Implementers for that set run as parallel
background tasks in separate worktrees — but integration stays SERIAL through atomic
`cairn merge`, one ticket at a time, rebasing the next worktree after each merge lands.
**Parallelism in the work, never in the merge** — merge conflicts are the failure mode that
costs the most operator attention.

## Scale envelope

Cairn is tested (`tests/test_scale.py`, marker `scale`) at **1,000 board tickets** (chain +
diamond dependency mix, 200 simultaneously ready) and **10,000 vault bullets** — an order of
magnitude beyond any realistic mission — and every core op stays in single-digit milliseconds
against multi-second CI budgets. The core ops are linear or near-linear: `read_board` is one
file read + per-line validation, O(n); `next_ready`/`ready_all` build one `id→entry` dict and
sort, O(n log n); `parallel_safe` is greedy with pairwise file-overlap checks, O(k²·f) in the
k tickets taken; `find_cycle` is an iterative white/grey/black DFS, O(V+E); `status.render`,
`boarddoctor.diagnose`, and `vaultcompact.plan` are single-pass O(n); `vaultio.search` scans
each vault file once, O(total lines). The only super-linear-feeling surface is `reconcile`,
which shells out to git per ticket — its cost is subprocess + repo state, not Cairn's
algorithms, so it is deliberately outside the perf-budget suite.

## Module map — `bin/cairn_core/`

The CLI entrypoint (`bin/cairn`) is argument parsing only; logic lives in `cairn_core`:

| Module | Owns |
|---|---|
| `board.py` | `board.jsonl` storage — atomic single-writer writes, `FORMAT_VERSION = 2`, natural-sort ids, dependent-guarded remove |
| `boardcheck.py` | validation rules for board entries (id/branch charsets, status enum, required `base_sha` on dispatch) |
| `resolve.py` | next-ready resolution over the DAG — `next_ready`, `ready_all`, `parallel_safe` (files_owned-disjoint sets), cycle/missing-dep diagnosis, `cancel_impact` |
| `runloop.py` | `cairn step` (the atomic loop iteration → dispatch JSON) + `cairn run-lock` (token mint/verify/heartbeat/steal) |
| `mergeflow.py` | `cairn merge` — atomic commit → rebase → `--no-ff` merge → board update → worktree removal |
| `reconcile.py` | `classify_ticket_state` — desired(board) vs actual(git), `base_sha`-disambiguated |
| `readiness.py` | the 8-check agent-readiness scorer behind `cairn readiness` / `/cairn-readiness` |
| `status.py` | board-as-table rendering, including >2h STALE notes from `dispatched_at` |
| `init.py` | mode detection + `.cairn/` scaffold (writes `meta.json` format stamp) |
| `vaultio.py` | append-only vault writers + ranked multi-term `search` (hit count, recency tiebreak, scope/limit) |
| `dismisscmd.py` / `dismiss_filter.py` | session-end harvest command + the durable-fact relevance filter (fallback memory path) |
| `handoff.py` | portable resume packs |
| `maprender.py` | `vault/map.md` rendering/merging (tooling + capability index) |
| `adapter.py` | optional Serena / claude-mem mirroring (never a hard dependency) |
| `specgraph.py` / `spec_html*.py` / `speccmd.py` | Mermaid + self-contained interactive HTML spec graph |
| `safepath.py` / `safepath_fd.py` | symlink/escape guards; dir-fd-anchored I/O (see security model) |

## Portability story — Claude Code / Cursor / Codex

The `.cairn/` core is tool-agnostic markdown + JSONL plus a `PROTOCOL.md` that any agent can
follow by hand. **Inside Claude Code**, the plugin's commands, agents, and SessionEnd hook
*automate* driving the loop and harvesting memory. **Outside Claude Code** — in Cursor or
Codex — a human or agent reads `PROTOCOL.md`, runs the same `cairn` CLI commands manually
(`cairn init`, `cairn next`, `cairn board set ...`), and reads/writes the same vault. The
`cairn-handoff` resume pack and the committed vault are the portable bridge: end a session in
Claude Code, pick it up in Cursor, and the memory + ticket state are exactly where you left
them. Optional `cairn-adapter` mirrors vault writes into Serena/claude-mem when present, with
a silent flat-file fallback — never a hard dependency.

## Security model

The plugin auto-runs hooks against whatever repo it lands in, so a **malicious repo** is part
of the threat model: it could plant a symlink under `.cairn/` (or ship `.cairn` itself as a
symlink) to trick an auto-running hook into reading, appending to, overwriting, or deleting
files **outside** the repo. Cairn defends against this class of symlink / path-traversal /
TOCTOU attack with **dir-fd-anchored I/O** (`bin/cairn_core/safepath_fd.py`): every read,
write, append, mkdir, unlink, atomic replace, and lock-open walks to its parent one component
at a time from a descriptor rooted at `realpath(.cairn)`, opening each step with
`O_DIRECTORY|O_NOFOLLOW` via `dir_fd=`. The final commit (`atomic_write`) creates a unique
sibling temp with `O_CREAT|O_EXCL|O_NOFOLLOW` and renames it onto the target with
**renameat** (`os.replace(..., src_dir_fd=, dst_dir_fd=)`); the board lock is opened with
**openat** (`open_lock_fd`). Because the kernel resolves these relative to a held, validated
fd, there is **no pathname re-resolution left to race** — a parent directory swapped to a
symlink between check and syscall cannot be followed.

**Residual risk (accepted):** on exotic platforms lacking `os.supports_dir_fd` for the needed
syscalls (`_SUPPORTS_DIR_FD` is False) the helpers fall back to check-then-open / `mkstemp` +
`os.replace` by pathname, which cannot fully close the parent-swap TOCTOU window. macOS,
Linux, and the BSDs all support `dir_fd`, so the race-free path is always taken on realistic
deployment targets; the only residual is those exotic platforms, an accepted risk for a local,
single-user tool.
