# s1-resume — finish a feature after a hard mid-flight kill

**Question:** after a hard session kill at the feature's halfway point, does the
resume session pick up the remaining tickets *without re-planning*, re-editing
finished work, or losing ledger/git sync?

## Task DAG (notes-cli, 6 tickets)

```
T01 storage ──> T02 model ──> T03 add ─────────┐
                       └────> T04 list ──> T05 search ──> T06 cli wiring
                              (T06 depends on T03 + T04 + T05)
```

Each ticket owns exactly one file (see `s1-resume.json` → `files_owned`), so
drift is unambiguous: any edit outside the assigned tickets' files is a
wrong-file edit.

## Session plan

| # | Kind   | Assigned tickets | Boundary |
|---|--------|------------------|----------|
| 1 | work   | T01, T02, T03    | HARD KILL (process exits; fresh context next) |
| 2 | resume | T04, T05, T06    | end of run |

## Condition difference under test

- **A (Cairn):** session 2 resumes from `.cairn/board.jsonl` + `.cairn/vault/`
  (the `/cairn-resume` flow).
- **B (control):** session 2 has only the prose notes in `CLAUDE.md`.

## Pass criteria (scored, see evals/README.md rubric)

- All 6 tickets completed and ledger-marked `[merged]`, each with a matching
  `feat(Txx):` commit (integrity_errors = 0).
- `checks.forbid_replanning`: the resume session must continue the existing
  plan — emitting a fresh plan counts as a replanning event (−5).
- Zero wrong-file edits; minimal re-explanation tokens.
