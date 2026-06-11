# s2-toolswitch — portable handoff to a different coding tool

**Question:** can a *different* tool resume the work from the handoff pack
alone? This tests Cairn's portability claim: memory should survive not just a
session kill but a tool switch (Claude Code → Cursor/Codex-style consumer).

## Task DAG (webhook-relay, 4 tickets)

```
T01 verify ──┐
             ├──> T03 dispatch ──> T04 replay
T02 registry ┘
```

## Session plan

| # | Kind   | Assigned   | Notes |
|---|--------|------------|-------|
| 1 | work   | T01, T02   | runs in the 'claude' condition tooling; **writes a handoff pack** before the HARD KILL |
| 2 | resume | T03, T04   | prompt simulates a DIFFERENT tool: its only permitted context is the handoff pack (`context: "handoff-only"`) |

## Condition difference under test

- **A (Cairn):** session 1 emits `.cairn/handoff.md` (the `/cairn-handoff`
  portable resume pack: board summary + open tickets + recent decisions).
  Session 2's prompt says: "You are a different coding tool; your ONLY context
  is the handoff pack."
- **B (control):** there is no structured pack format; session 2 may read
  `HANDOFF.md` if session 1 happened to write one, else falls back to
  `CLAUDE.md` prose.

## Pass criteria

- Session 2 completes T03 + T04 with correct `feat(Txx):` commits and ledger
  updates, having read only the pack (`checks.handoff_only_resume`).
- No re-implementation of T01/T02 files (wrong-file edits = 0).
- No fresh plan emitted (`checks.forbid_replanning`).
