# Security

## Model

Cairn's CLI runs inside AI-agent sessions against repos it does not trust:

- **Path safety**: every read/write under `.cairn/` is dir-fd-anchored
  (`openat`/`renameat`, `O_NOFOLLOW`, `O_EXCL` locks) — a planted symlink or swapped
  parent directory is refused at the kernel level, with no pathname re-resolution to race.
- **Git argument safety**: ticket ids, branch names, and base refs are charset-validated
  (no leading `-`, no `..`, no git-forbidden patterns) and passed after `--end-of-options`.
- **Single-writer board**: only the orchestrator session writes `board.jsonl` and the vault;
  subagents return summaries. A token run-lock prevents concurrent reconciler sessions.
- **Workflow templates** (`integrations/github/`) use env indirection for every GitHub
  context value — nothing untrusted is interpolated into `run:` scripts — and the PR bot
  gates on author association with an allowlisted-keyword command parser.

## Reporting

Open a GitHub issue with the `security` label, or use GitHub's private vulnerability
reporting on this repository. Please do not include exploit details in public issues.
