---
name: cairn-adapter
description: Thin detect+mirror layer for optional memory-enrichment engines. Detects Serena (mcp__plugin_serena_serena__*) and claude-mem (mcp__plugin_claude-mem_*); mirrors vault writes into them and routes recall queries to them when present. Silent flat-file fallback if absent — NEVER a hard dependency. Use from cairn-vault/cairn-map/cairn-recall/cairn-dismiss to enrich memory when those engines happen to be installed.
---

# cairn-adapter

Make Serena/claude-mem **accelerators**, never **requirements**. Detect what is installed,
mirror flat-file vault writes into it, route recall to it — and fall back to flat files
silently when nothing is present.

## Detection
The engines announce themselves as MCP tools. Detect by tool-name prefix:
- **Serena** → any tool starting `mcp__plugin_serena_serena__`
- **claude-mem** → any tool starting `mcp__plugin_claude-mem_`

The routing logic lives in `cairn_core/adapter.py` (`detect_engines`, `plan_mirror`,
`plan_recall`) and is fully tested with injected presence flags — so behavior is identical
whether or not the real MCPs exist.

## Mirror a vault write
After any flat-file vault append, ask `plan_mirror(present, name, text)` for routes:
- Serena route → `write_memory` keyed `cairn/<name>`.
- claude-mem route → `memory_add` in category `<name>`.
Execute each route via its MCP tool. **Empty routes => do nothing** (flat file is the source
of truth; the engine is a bonus index).

## Route a recall
`plan_recall(present, query)` returns `mode=engine` (with the engine list) when present, else
`mode=grep`. For `engine`, run the semantic query through the listed engine(s); for `grep`,
defer to `bin/cairn recall "<query>"`.

## Rules (non-negotiable)
- **Never a hard dependency.** Absence of both engines is the normal case and must work with
  zero errors and zero degraded correctness — only speed/semantics differ.
- The flat-file vault is always authoritative. Engines are a mirror/index, never the source
  of truth.
- No auto-commit/push.
