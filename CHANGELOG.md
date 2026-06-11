# Changelog

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
