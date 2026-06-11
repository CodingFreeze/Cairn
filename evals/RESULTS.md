# Continuation Eval Results

> **No public results yet — run `python3 evals/continuation/runner.py --mock`
> to validate the harness; real runs require claude CLI + API budget.**
>
> Mock-mode numbers are synthetic by construction (the mock scripts the
> failure modes the harness must detect) and must never be quoted as evidence
> for or against the thesis. This page stays in this pending state until a
> real run (mode `"real"` in the results JSON) is published with its model id,
> CLI version, seeds, and raw `evals/results/<timestamp>.json` attached.

## Template (filled from a real run's per-cell aggregates)

Status: **PENDING** · Model: _n/a_ · CLI: _n/a_ · Seeds: _n/a_ · Run file: _n/a_

| Scenario | Condition | Score (0–100) | Tickets done | Integrity errors | Re-explanation tokens | Wrong-file edits | Re-planning events |
|---|---|---|---|---|---|---|---|
| s1-resume | Cairn | — | —/6 | — | — | — | — |
| s1-resume | control | — | —/6 | — | — | — | — |
| s2-toolswitch | Cairn | — | —/4 | — | — | — | — |
| s2-toolswitch | control | — | —/4 | — | — | — | — |
| s3-return | Cairn | — | —/5 | — | — | — | — |
| s3-return | control | — | —/5 | — | — | — | — |

All values are means across seeds; per-seed values live in the run JSON.

## Publishing checklist

- [ ] Real run (`mode: "real"`), 3+ seeds, both conditions, all scenarios
- [ ] Model id + claude CLI version pinned and recorded
- [ ] Raw results JSON committed to `evals/results/`
- [ ] Session records spot-checked (completion isn't gamed — see README
      threat 6)
- [ ] Threats-to-validity section reviewed against what actually happened
- [ ] If the data refutes or weakens the thesis, publish it anyway
