---
name: cairn-dismiss
description: Session-end memory harvest. Scans the live conversation for durable, reusable facts not yet in the vault and writes them to decisions/issues/schema/map plus refreshes handoff/latest.md. Triggers — SessionEnd hook (primary, deterministic), the keyword "dismissed", the --cairn-dismissed flag, or an optional model soft-sense nudge. Use when a session is wrapping up so conversational intelligence is not lost when the window closes.
---

# cairn-dismiss

Close the "lost conversational intelligence" gap: capture decisions/gotchas/schema spoken in
a session before the window dies.

## Triggers (most to least reliable)
1. **SessionEnd/Stop hook** (primary, deterministic) — `hooks/cairn-dismiss-hook.sh` refreshes
   the handoff pack on every session end and harvests any candidate set an active session
   staged. No human in the loop => silent.
2. **Keyword `dismissed`** — composes with the operator's *global* dismissed protocol. Global
   handles plugin-disable/lessons; cairn handles the `.cairn` vault harvest. **Compose, do not
   collide:** run the cairn harvest as one step of the wind-down, do not duplicate or block the
   global steps.
3. **Flag `--cairn-dismissed`** — explicit on-demand harvest.
4. **Model soft-sense** — optional nudge only ("seems like we're wrapping — run cairn-dismiss?").
   Never primary.

## Harvest procedure
1. **Gather candidates** from the conversation as `{"kind","text"}` objects, where kind is one of
   `decisions | issues | schema | map`:
   - decisions made -> `decisions`
   - gotchas / known issues + remedies -> `issues`
   - data contracts / schema -> `schema`
   - repo facts / where-things-live / tooling -> `map`
2. **Filter + write** via the CLI (the relevance filter + single-writer append + handoff
   refresh all run inside it):
   ```bash
   bin/cairn dismiss '[{"kind":"decisions","text":"Chose flat-file vault as source of truth"}]'
   ```
   The filter keeps only durable/reusable facts, dedupes, and skips anything already in the
   vault. It then rewrites `handoff/latest.md`.
3. **Mirror** the captured facts via the `cairn-adapter` skill if an engine is present.

## Write mode
- **Hook-triggered (no human watching)** -> write silently, then log what was captured.
- **Explicit `dismissed` / `--cairn-dismissed` (human present)** -> show the capture summary
  FIRST, write only on confirmation.

## Safety rails (non-negotiable)
- **Relevance filter** — durable/reusable facts only; chatter and fragments are dropped.
- **Single-writer, append-only** — never clobbers prior vault entries.
- **No auto-commit/push** — writes touch files only; commit requires operator permission.

## Composing with the global "dismissed" protocol
When the global protocol runs (plugin-disable, lessons, vault artifacts), cairn-dismiss is the
project-memory step: it harvests `.cairn` conversational facts. It must not re-run the global
steps, must not commit, and must not block the wind-down.
