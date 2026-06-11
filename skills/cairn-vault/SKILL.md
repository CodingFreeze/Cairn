---
name: cairn-vault
description: Initialize and maintain the durable git-native .cairn/ vault in ANY repo — even without orchestration. Wraps `cairn init` and provides append-only writes to schema/decisions/issues/map that never clobber prior memory. Use when the user wants to start persistent project memory, record a decision, log a gotcha, or capture a data contract.
---

# cairn-vault

Stand up and feed the durable vault. The vault is the moat: flat markdown committed to git
that survives session death and travels across Claude Code / Cursor / Codex.

## When to use
- "Start tracking decisions for this project" → init the vault.
- "Remember that we decided X" → append to `decisions`.
- "Note this gotcha / known issue" → append to `issues`.
- "Record this data contract / schema" → append to `schema`.

## How it works
The shipped `bin/cairn` CLI is the single writer. Appends use `vaultio.append`, which opens
files in append mode — it is physically incapable of clobbering prior entries.

## Steps
1. **Ensure the vault exists.** Run `bin/cairn init` (auto-detects greenfield vs existing).
   Idempotent: re-running never overwrites existing vault files.
2. **Append a durable fact** to the right file:
   ```bash
   bin/cairn vault append decisions "Chose flat-file vault as the source of truth"
   bin/cairn vault append issues    "tests flaky on CI; remedy: pin tz to UTC (applies-to: future)"
   bin/cairn vault append schema    "users table: id (uuid pk), email (unique), created_at"
   bin/cairn vault append map       "auth logic lives in src/auth/*"
   ```
   Allowed files: `schema`, `decisions`, `issues`, `map`. Any other name is rejected.
3. **Mirror to enrichment engines** if present — delegate to the `cairn-adapter` skill (silent
   flat-file fallback if Serena/claude-mem are absent). Never a hard dependency.

## Rules (non-negotiable)
- **Single-writer:** only the live orchestrator/session writes the vault. Subagents return
  summaries; they do not write here.
- **Append-only:** never edit or delete prior entries.
- **No auto-commit/push:** writes touch files only. Commits require operator permission.
