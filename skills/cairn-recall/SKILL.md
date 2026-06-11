---
name: cairn-recall
description: Query the durable .cairn vault across sessions — "what did we decide about auth?", "any known issues with the build?". Tries an enrichment engine (Serena / claude-mem) via cairn-adapter first for semantic recall; otherwise greps the flat-file vault. Use when the user asks about past decisions, prior gotchas, established schema, or where something lives.
---

# cairn-recall

Answer cross-session questions from durable memory. Memory survives session death, so this
works even in a brand-new session of any tool.

## When to use
- "What did we decide about X?"
- "Have we hit this bug before? What was the fix?"
- "What's the schema for Y?" / "Where does Z live?"

## Routing (engine-first, grep-fallback)
1. Ask the `cairn-adapter` skill which enrichment engines are present (`detect_engines`).
2. **If Serena/claude-mem present** → run the semantic query through them (adapter
   `plan_recall` returns `mode=engine`), then cross-check against the flat-file vault for
   completeness.
3. **If none present** → fall back to flat-file grep (always available, never errors):
   ```bash
   bin/cairn recall "auth"
   ```
   This scans `decisions.md`, `issues.md`, `schema.md`, `map.md` for matching bullets.

## Output
Summarize the matching entries grouped by file (decisions / issues / schema / map). Quote the
relevant bullets so the user sees the source. If nothing matches, say so plainly — do not
invent memory.

## Rules
- Read-only. Recall never writes the vault.
- The enrichment engine is an accelerator, never a requirement.
