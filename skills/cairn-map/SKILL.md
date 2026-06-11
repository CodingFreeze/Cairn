---
name: cairn-map
description: Generate or refresh the repo-warmth map at .cairn/vault/map.md — where things live, key symbols, gotchas, PLUS a Tooling / capability index of which tools, skills, and MCPs the project uses and when. The tooling index is inherited by every session and injected into per-ticket dispatch prompts. Use when onboarding to a codebase, after big structural changes, or when the dispatch prompts need to know the project's toolset.
---

# cairn-map

Build the repo's warmth file so a cold session re-hydrates fast, and record the project's
toolset so dispatched implementers know what they can use.

## When to use
- First time working in a repo (onboarding / `--existing` mode).
- After moving/renaming major modules.
- When a new tool/skill/MCP becomes part of the project's workflow.

## Steps
1. **Ensure the vault exists:** `bin/cairn init`.
2. **Survey the repo.** Identify entry points, where core logic lives, key symbols, and known
   gotchas. If Serena is present (see `cairn-adapter`), use its symbol tools for a faster,
   accurate map; otherwise inspect the tree and source directly.
3. **Refresh "Where things live"** in `.cairn/vault/map.md` with concise bullets:
   ```bash
   bin/cairn vault append map "entry point: src/index.ts; HTTP routes in src/routes/*"
   bin/cairn vault append map "gotcha: db migrations must run before tests (see Makefile)"
   ```
4. **Build the Tooling / capability index.** Detect which tools/skills/MCPs the project uses
   (test runner, linter, security scanner, Serena/claude-mem, framework CLIs) and when each
   applies. Record them so they survive into every future session and every dispatch prompt:
   ```bash
   bin/cairn vault append map "tooling: pytest (tool) — run tests; semgrep (MCP) — security gate on PRs"
   ```
   This index is the slice of memory injected into per-ticket dispatch prompts in Plan 3's
   orchestration loop, so the implementer knows its toolset without re-discovery.

## Rules
- Single-writer, append-only, no auto-commit (same as `cairn-vault`).
- Keep `map.md` under 300 lines — prune stale bullets rather than letting it sprawl.
