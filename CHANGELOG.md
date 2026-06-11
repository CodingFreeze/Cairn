# Changelog

## v0.3.0 — Continuation proven, teams unlocked (2026-06)

- **Continuation eval harness** (`evals/`): paired-condition benchmark (Cairn vs CLAUDE.md-only),
  3 scenarios, git-ground-truth metrics, offline `--mock` mode for CI. Results pending first
  public run — template ships honest.
- **`cairn mission`**: live dashboard — board.jsonl -> animated DAG + status feed + vault tail,
  localhost-only, XSS-safe; replay demo mode bundled.
- **Team vault mechanics**: init scaffolds `.cairn/.gitattributes` (union merge for vault/handoff);
  `cairn board doctor [--apply]` repairs merge damage (duplicate ids, malformed lines -> .rej).
- **Contracts as code**: `.cairn/contracts/<name>.schema.json` artifacts; `cairn contract add|check`;
  merge gate (warn by default, `strict_contracts` aborts pre-mutation on errors).
- **GitHub Issues sync**: `cairn sync push|pull [--apply]` — report-first plans, mapping in
  `.cairn/sync.json`, git truth never overruled by issue state.
- **`cairn vault compact`**: deterministic dedupe + archive-keep-N, LLM-free.
- **CI**: ubuntu/macos × py3.9/3.12 matrix gate, experimental Windows lane, tag-driven releases.
- Case study (`docs/CASE-STUDY.md`) + public `ROADMAP.md`.
- Suite: 425 -> 537 tests.

## v0.2.0 — Factory parity (2026-06)

- **Loop as code**: `cairn step` — each reconciler iteration is one atomic, tested CLI call
  (pick → worktree → record base SHA → flip board → emit dispatch JSON). `cairn run-lock`
  (token + exclusive create) closes the concurrent-session race.
- **Board format 2**: `base_sha` required on dispatch, staleness detection (STALE notes),
  `cancelled` status, dependent-guarded `board remove [--force]`, natural-sort ticket ids,
  branch charset + git-forbidden-pattern validation.
- **Autonomy ladder + per-role model routing** via `.cairn/config.json` — picked at the
  plan approval gate (`manual` / `merge-on-green` / `full-auto`; cheap workers, strong validators).
- **Parallel work, serial merge**: `cairn ready --parallel` (files-owned-disjoint set);
  integration stays atomic through `cairn merge`.
- **New surfaces**: `/cairn-rca` (incident → RCA → fix ticket), `/cairn-readiness`
  (8-check agent-readiness score + fixes), `cairn-security` agent (OWASP/secrets diff gate).
- **Integrations**: headless CI workflow, `@cairn` PR bot, Linear/Jira/Sentry MCP flows,
  `#remember` inline memory capture, ranked vault recall.
- 425 tests; dir-fd-anchored I/O hardening throughout.

## v0.1.0 — Foundation

- Spec-mode planning (`/cairn-plan`): ticket DAG, schema layer, interactive spec graph.
- Reconciler loop (`/cairn-run`): worktree-isolated implementer/reviewer/tester dispatch.
- Git-committed memory vault (schema / decisions / issues / map) + handoff packs
  (portable to Cursor and Codex).
- Atomic `cairn merge`; symlink/TOCTOU-hardened file I/O (openat/renameat).
