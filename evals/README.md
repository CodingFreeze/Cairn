# Cairn Continuation Evals

A runnable benchmark for Cairn's core thesis:

> **Agents continue multi-session work better with Cairn than with CLAUDE.md
> alone.**

This harness exists to *prove or refute* that claim, not to decorate it.
Until a real run is published, every number it can produce is marked pending
or mock — see [RESULTS.md](RESULTS.md).

## Design: paired conditions

Every scenario runs under two conditions on an otherwise identical setup
(same fixture repo, same seeded task DAG, same session plan, same prompts up
to the memory-layer instructions):

| | Condition A — Cairn | Condition B — control |
|---|---|---|
| Memory layer | `.cairn/` vault (`decisions.md`, `issues.md`, `map.md`) + `board.jsonl` ticket ledger | prose notes + a ticket-status list in `CLAUDE.md` only |
| Resume flow | `/cairn-resume`-style: read board + vault, continue | re-read `CLAUDE.md`, continue |
| Handoff (s2) | `/cairn-handoff` portable pack (`.cairn/handoff.md`) | whatever notes the session left (`HANDOFF.md` if any, else `CLAUDE.md`) |

Both conditions maintain a ticket ledger so the board-vs-git integrity metric
is computed **symmetrically** (`metrics.parse_board_jsonl` vs
`metrics.parse_control_ledger` produce the same entry shape).

## Protocol

1. **Seeded task list.** Each scenario ships a fixed task DAG fixture
   (`continuation/scenarios/*.json`): tickets with `depends_on` edges and
   exclusive `files_owned` (making drift unambiguous).
2. **N sessions with hard kills.** The scenario's session plan is executed as
   separate `claude -p <prompt> --output-format json` subprocesses. A session
   ends when the process exits (or hits `--session-timeout`); **nothing
   survives the kill except the repo on disk** — the next session is a fresh
   context. No conversation continuation flags are ever passed.
3. **Fixed model + prompt budget.** One model per run (`--model` /
   `$CAIRN_EVAL_MODEL`, recorded in the results JSON), fixed prompt templates
   (`runner._build_prompt`), fixed per-session wall-clock budget.
4. **3 seeds.** Each (scenario × condition) cell runs with seeds `1,2,3`
   (`--seeds`); published numbers are per-cell means across seeds.

## Scenarios

| id | Tests | Plan |
|---|---|---|
| [s1-resume](continuation/scenarios/s1-resume.md) | resume after mid-feature kill | 6 tickets; kill after T03; resume session must finish T04–T06 without re-planning |
| [s2-toolswitch](continuation/scenarios/s2-toolswitch.md) | portable handoff | session 1 ('claude' condition) writes a handoff pack; session 2's prompt simulates a different tool whose only context is the pack |
| [s3-return](continuation/scenarios/s3-return.md) | recall precision | kill; unrelated distractor task; then resume — must pick up the feature, not the distractor |

## Metrics (as implemented in `continuation/metrics.py`)

| Metric | Definition |
|---|---|
| `tickets_completed` | tickets with a matching `feat(<id>):` commit — **git is ground truth** of work done |
| `integrity_errors` | board-vs-git mismatches, both directions: ledger-done with no commit + committed with no ledger-done |
| `re_explanation_tokens` | for each *resume* session: input tokens consumed beyond the bare task instruction — i.e. prompt tokens spent re-establishing context |
| `wrong_file_edits` | drift: files edited in a work/resume session outside the assigned tickets' `files_owned` (memory-layer files exempt; distractor sessions excluded) |
| `replanning_events` | resume sessions that emitted a fresh plan instead of continuing (real mode detects via a `# Plan` header heuristic — see threats) |

## Scoring rubric → `composite_score` (0–100)

| Component | Points | Formula |
|---|---|---|
| Completion | 50 | `50 × completion_rate` |
| Integrity | 20 | `max(0, 20 − 10 × integrity_errors)` |
| Drift | 15 | `max(0, 15 − 5 × wrong_file_edits)` |
| Efficiency | 15 | `15 / (1 + re_explanation_tokens / 1000)` |
| Re-planning penalty | −5 each | per replanning event; total floored at 0 |

## Running

```sh
# Validate the harness itself — offline, deterministic, zero API spend:
python3 evals/continuation/runner.py --mock

# Real run (requires the claude CLI and API budget):
CLAUDE_BIN=claude python3 evals/continuation/runner.py --seeds 1,2,3 \
    --model <model-id>

# One cell:
python3 evals/continuation/runner.py --mock --scenario s1-resume \
    --condition cairn --seeds 1
```

Results land in `evals/results/<timestamp>.json` with `mode`, `model`,
`seeds`, per-seed metrics, per-cell aggregates, and the full session records.
**Mock results carry an explicit disclaimer and are never evidence** — the
mock executor (`continuation/mock_session.py`) scripts the very failure modes
the harness must detect, which validates the pipeline and nothing else.

## Threats to validity (read before quoting numbers)

1. **Single task family per scenario.** Three small greenfield Python features
   (CLI, webhook relay, config loader). Results may not transfer to large
   brownfield repos, refactors, or debugging work. Mitigation: tickets have
   exclusive file ownership so the drift metric stays unambiguous; extending
   the scenario set is the roadmap, not a claim.
2. **Model nondeterminism.** A single run per cell proves nothing. Mitigation:
   3 seeds per cell, means reported, per-seed values retained in the JSON —
   but 3 is a floor for sanity, not statistical power. No significance claims
   without many more runs.
3. **Author bias in prompts.** The same people who built Cairn wrote both
   conditions' prompts. We keep the prompts minimal and symmetric (diff
   `runner._build_prompt`), but an adversarially-tuned control prompt could
   narrow the gap. The prompts are in the repo precisely so you can challenge
   them.
4. **Heuristic re-planning detection (real mode).** A `# Plan` header in the
   session result is a crude proxy; it can miss re-planning expressed in prose
   and false-positive on quoted headers. Treat `replanning_events` as the
   weakest real-mode metric.
5. **Token accounting.** `task_prompt_tokens` is estimated at 4 chars/token in
   real mode; `re_explanation_tokens` is therefore approximate (consistent
   across conditions, so the *comparison* is fairer than the absolute value).
6. **Harness-as-judge.** Completion is "a conventional commit exists per
   ticket", not "the code is good". A session could game this; manual spot
   checks of session records are part of the publishing protocol.
7. **CLI version drift.** `claude -p --output-format json` output shape may
   change; the run records the binary used. Pin your CLI version when
   publishing.

## Layout

```
evals/
  README.md                    this file (methodology)
  RESULTS.md                   published results (pending until a real run)
  results/                     run outputs: <timestamp>.json (git-ignored except .gitkeep)
  continuation/
    runner.py                  orchestration + real-session execution
    mock_session.py            deterministic offline session executor
    metrics.py                 pure metric functions
    scenarios/s{1,2,3}-*.{md,json}   scenario specs + task DAG fixtures
```

Tested by `tests/test_evals_harness.py` (runs `--mock` end-to-end plus metric
unit tests) as part of the main suite (`scripts/test.sh`).
