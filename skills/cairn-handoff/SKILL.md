---
name: cairn-handoff
description: Emit .cairn/handoff/latest.md — a portable resume pack (board summary + open tickets + recent decisions/issues) so a fresh Claude Code / Cursor / Codex session resumes cleanly. Use when wrapping up, switching tools, before a context-window reset, or when the user asks for a handoff / resume pack / "where were we".
---

# cairn-handoff

Produce a single portable file that lets any new session pick up exactly where this one left
off — without the original context window.

## When to use
- Switching from Claude Code to Cursor/Codex (or vice versa).
- Before a long break or a context reset.
- "Give me a handoff" / "summarize where we are".

## Steps
1. **Ensure the vault exists:** `bin/cairn init` (no-op if already present).
2. **Generate the pack:**
   ```bash
   bin/cairn handoff
   ```
   This writes `.cairn/handoff/latest.md` from `board.jsonl` + vault files:
   - **Board summary** — every ticket with status / deps / branch.
   - **Open tickets** — anything not yet merged.
   - **Recent decisions** and **recent issues/remedies** — the last few vault entries.
3. **Surface it.** Show the path and the pack contents to the user; it is committed with the
   rest of `.cairn/` only when the operator chooses to commit.

## Rules
- Read-from-board, write-only-to-handoff. Does not mutate the board or other vault files.
- No auto-commit/push.
