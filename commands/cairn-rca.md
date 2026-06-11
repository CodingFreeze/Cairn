---
name: cairn-rca
description: Root-cause analysis from a failure artifact — a log file, pasted stack trace, error message, or failing CI output. Correlates the failure signature with recent commits and prior vault issues, appends an RCA note to vault/issues.md, and proposes a board-registered fix ticket (F##). Factory Reliability-Droid parity, local form.
argument-hint: "<log-file-path | pasted stack trace | error message | CI output>"
---

# cairn-rca — artifact → root cause → fix ticket

You are the **orchestrator** for this session — the SOLE writer to `.cairn/board.jsonl` and
`.cairn/vault/`. Factory routes alerts through a Reliability Droid; Cairn's local form drives
any failure artifact to a durable RCA note plus a fix ticket the reconciler can drain.

> **Invocation:** if `cairn` is not on `PATH`, call `python3 <plugin-dir>/bin/cairn`.

## 0. Load correlation context
- Read `.cairn/vault/issues.md` — prior failures + remedies (the fix-forward ledger).
- `git log --oneline -20` — the recent-change window the failure most likely lives in.

If `.cairn/` is missing, STOP — tell the operator to run `/cairn-plan` (or `cairn init`) first.

## 1. Parse the artifact
`$ARGUMENTS` is either a file path (read it — for large logs, tail the last ~200 lines first)
or pasted text. Extract the **failure signature**:
- exception type / error code + message;
- innermost in-repo frame(s) → the implicated file paths (+ lines);
- first-bad timestamp or CI job/step, if present.

State the signature in one line before moving on.

## 2. Correlate
- **Recent commits touching the implicated paths:**
  ```bash
  git log --oneline -10 -- <implicated paths>
  git log -p -3 -- <implicated paths>   # read the actual diffs, newest first
  ```
- **Prior occurrences:** `cairn recall "<signature terms>"` — a prior issues.md entry with the
  same signature usually already carries the remedy; if so, say so and prefer it.

Form a root-cause hypothesis: signature → suspect commit/diff → mechanism. If the evidence is
ambiguous, present the top two candidates and ask the operator BEFORE writing anything.

## 3. Write the RCA note (single-writer: you)
One durable, greppable line:
```bash
cairn vault append issues "RCA $(date +%F): <signature> → <root cause> → <remedy> (suspect: <sha>)"
```

## 4. Propose the fix ticket
Find the next free `F##` (`cairn board list`; max existing F-id + 1, else `F01`). Then:
1. Write `.cairn/tickets/F##.md` — same shape as T-tickets: Goal (one sentence), Acceptance
   criteria (MUST include "regression test reproducing the failure passes"), Files owned =
   the implicated paths, Notes = the RCA line + suspect sha.
2. Register it on the board:
   ```bash
   cairn board add '{"id":"F##","depends_on":[],"files_owned":["<implicated paths>"]}'
   ```

## 5. Offer the run
Ask the operator: run `/cairn-run` now to drive `F##` through implement → review → test →
merge? Do NOT start it without an explicit yes.

## Rules
- **Single-writer:** only this orchestrator session writes board + vault. Never dispatch an
  agent to write them.
- Evidence before assertion — name the suspect commit, or say "unconfirmed" out loud.
- No commits/pushes without operator permission.
