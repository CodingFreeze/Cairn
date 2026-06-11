# s3-return — resume after an intervening distractor task

**Question:** when the agent is killed mid-feature, given an *unrelated* task,
and only then asked to resume — does it recall the right thread (recall
precision), or does it blend the distractor into the feature work?

## Task DAG (config-loader, 5 tickets)

```
T01 defaults ──> T02 file layer ──┐
        └──────> T03 env layer ───┴──> T04 merge ──> T05 validate
```

## Session plan

| # | Kind       | Assigned       | Notes |
|---|------------|----------------|-------|
| 1 | work       | T01, T02       | HARD KILL |
| 2 | distractor | (none)         | unrelated docs task (`docs/changelog-tool.md`); HARD KILL |
| 3 | resume     | T03, T04, T05  | must resume the FEATURE, not the distractor |

## What recall precision means here

The distractor session is excluded from drift scoring (it is off-task by
design). The resume session is where precision is measured:

- touching `docs/changelog-tool.md` again → wrong-file edit (recalled the
  wrong thread);
- re-editing T01/T02 files → wrong-file edit (lost completed-state recall);
- emitting a fresh plan → replanning event.

## Condition difference under test

- **A (Cairn):** the board pins ticket state; the vault's decisions log marks
  the distractor as out-of-band, so session 3's `/cairn-resume` lands on
  T03–T05 directly.
- **B (control):** `CLAUDE.md` prose must carry both the feature state and the
  fact that the distractor was unrelated — precision depends entirely on how
  well session 1/2 happened to write notes.

## Pass criteria

- T03–T05 completed with matching commits and ledger entries; integrity = 0.
- Wrong-file edits = 0 in session 3; no replanning.
