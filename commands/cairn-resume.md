---
name: cairn-resume
description: Resume a Cairn run after session death. Reconciles board desired-state against git actual-state (cairn reconcile), re-enters each ticket at the correct point — re-dispatch, resume-at-review, or skip-merged — then continues the cairn-run loop. No orchestration state is read from memory; it is all rebuilt from disk.
argument-hint: "[--base <branch>]"
---

# cairn-resume — reconcile from disk, then continue

You are the **orchestrator**, restarted. You hold NO in-flight state — rebuild everything from
`board.jsonl` + git. This is the differentiator: session death is a non-event.

## 1. Read the actual-vs-desired diff
Run `cairn reconcile` (pass `--base` if the run used a non-main target). It returns JSON:
one `{id, status, branch, state}` per ticket where `state` in `needs_dispatch`,
`in_progress_resumable`, `needs_review`, `merged`, `conflict`.

## 2. Reconcile each ticket to the right re-entry point
Walk tickets in id order and act on `state`:

| state | meaning | action |
|-------|---------|--------|
| `merged` | git already integrated it (board may have lagged) | ensure `cairn board set <id> status=merged`; skip |
| `needs_review` | dispatched, branch HAS commits | **resume at the review step** — rebase-before-turn, then dispatch reviewer + tester (+ semgrep) on the existing branch; PASS->merge / FAIL->retry-once-then-block |
| `in_progress_resumable` | dispatched, branch exists but EMPTY | branch produced nothing — re-dispatch the implementer (fresh) on the existing branch |
| `needs_dispatch` | todo, or dispatched with NO branch | reset to a clean dispatch: `cairn board set <id> status=todo`, let the loop create the worktree/branch |
| `conflict` | branch diverged and rebase would clash | do NOT auto-resolve — `cairn board set <id> status=blocked`, append the conflict to `vault/issues.md`, surface to operator |

## 3. Continue the loop
After reconciling resumable/in-flight tickets, hand off to the **cairn-run** loop for any
remaining `todo`/`needs_dispatch` tickets (`cairn next` drives forward). Use the same rules:
rebase-before-turn, issues-ledger injection, sole-writer, merge-with-permission.

## Rules
- Read state ONLY from `cairn reconcile` + git — never assume in-memory state.
- Single-writer + no commit/push/merge without operator permission, same as cairn-run.
- Resuming `needs_review` MUST still rebase-before-turn — the base may have advanced while the
  session was dead.
