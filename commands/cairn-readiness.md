---
name: cairn-readiness
description: Score how agent-ready the repo is. Runs the `cairn readiness` CLI (JSON; score + per-check ok/detail/fix), renders the result as a table, then offers to scaffold each missing artifact (.gitignore, README, AGENTS.md, tests + smoke test, CI stub) — one operator approval per fix.
argument-hint: ""
---

# cairn-readiness — is this repo agent-ready?

Factory ships `/readiness-report`; this is Cairn's local form. Diagnose first; fix only with
per-item approval.

> **Invocation:** if `cairn` is not on `PATH`, call `python3 <plugin-dir>/bin/cairn`.

## 1. Run the checks
```bash
cairn readiness
```
JSON out: `{"score": <0-100>, "checks": [{"check": "...", "ok": true|false, "detail": "...", "fix": "..."}]}`.
(If the subcommand is missing — older CLI — perform the checks in step 3's list manually and
say you did.)

## 2. Render the report
One markdown table, one row per check, then the score line:

| Check | Status | Detail | Fix |
|---|---|---|---|
| tests | PASS / FAIL | <detail> | <fix — failing rows only> |

> `Readiness: <score>/100 — <n> of <m> checks passing.`

## 3. Offer fixes (per-item approval — MANDATORY)
For each FAILING check, offer its scaffold via **AskUserQuestion** — one decision per item,
"skip" always an option. Scaffolds are minimal skeletons; NEVER overwrite an existing file:
- **.gitignore** — language-appropriate ignores (build artifacts, caches, `.env*`, worktree dirs).
- **README.md** — skeleton: title, one-line description (from `.cairn/vault/goal.md` if present),
  setup, usage.
- **AGENTS.md** — skeleton: project layout, build/test commands, conventions agents must follow.
- **tests/ + first smoke test** — the project's native framework (e.g. pytest
  `tests/test_smoke.py` importing the package and asserting trivially); run it once to prove green.
- **CI workflow stub** — `.github/workflows/ci.yml` running the test command on push/PR. Quote
  interpolated values; NEVER put untrusted input in `run:` steps.

## 4. Re-score
After applying the approved fixes, re-run `cairn readiness` and report before → after.

## Rules
- Diagnose freely; **scaffold only with explicit per-item approval**.
- A scaffold target that already exists → report it and skip; never clobber.
- No commits/pushes without operator permission.
