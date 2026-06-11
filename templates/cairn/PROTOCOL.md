# Cairn Protocol

Rules any agent (Claude Code / Cursor / Codex) MUST follow when operating in this repo.

1. **Single-writer.** Implementer subagents write ONLY their own git worktree (code) and a
   return summary. The orchestrator (the live `cairn-run` session) is the SOLE writer to
   `board.jsonl` and everything under `vault/`. Never have two writers touch the board.
2. **Reconcile-from-disk.** All orchestration state lives in `board.jsonl`. A new session
   rebuilds actual-vs-desired from the board + git. Never keep orchestration state only in
   the live context.
3. **Rebase-before-turn.** Each ticket branch rebases on the integration target before its
   turn, so it inherits all previously merged fixes (fix-forward).
4. **Issues-ledger injection.** Every dispatch prompt includes `vault/issues.md` remedies so
   downstream tickets inherit known fixes.
5. **No auto-commit/push.** Memory writes go to files. Commits/pushes require operator
   permission.
