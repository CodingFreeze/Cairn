# Roadmap

> Honest status labels reflect merge state on main.
> **design** = shaped, not started. **exploratory** = direction, no commitment.
> Nothing below is shipped until it lands on `main` and the CHANGELOG says so.

## Just shipped (v0.2 — for orientation)

Loop-as-code (`cairn step`, `run-lock`), board format 2 with the required
`base_sha`, autonomy ladder + per-role model routing, parallel work / serial
merge, RCA + readiness surfaces, CI + PR-bot integrations. Full detail in the
[CHANGELOG](./CHANGELOG.md); the story behind it in the
[case study](./docs/CASE-STUDY.md).

## Near — shipped in v0.3.0

| Item | Status | What it is |
|---|---|---|
| Continuation eval results | shipped (v0.3.0) | The `evals/` benchmark from the [case study](./docs/CASE-STUDY.md): kill runs at adversarial points, measure cold-session reconvergence. Results get published, not summarized. |
| Mission live mode | shipped (v0.3.0) | A long-running mission surface over the reconciler — watch the board move ticket-by-ticket instead of polling `cairn status`. |
| Team vault mechanics | shipped (v0.3.0) | Multi-writer conventions for a shared `.cairn/`: merge-friendly vault folds, ownership rules, conflict story for two teammates' agents on one board. |
| Contracts as code | shipped (v0.3.0) | `vault/schema.md` prose contracts get a machine-checkable form — producers declare, consumers verify, the conform-or-explain rule becomes enforceable. |
| Issues sync | shipped (v0.3.0) | Two-way bridge between `board.jsonl` and external trackers (GitHub Issues first), building on the existing Linear/Jira MCP flows. |

## Mid — design

- **Vault compaction at scale.** Append-only `decisions.md` / `issues.md` are
  the right write path and the wrong read path after a few hundred entries.
  Planned: a compaction pass that summarizes cold entries while keeping the
  full log in git history — nothing is ever lost, recall stays fast.
- **Windows CI.** The core is stdlib Python, but the dir-fd hardening
  (`openat`/`renameat`) is POSIX-shaped. Windows needs an equivalent-safety
  fallback plus a CI lane proving it, not a caveat in the README.
- **GitHub-native team mode.** The pieces exist (headless CI runner, `@cairn`
  PR bot, PR-per-ticket has been a known want since the first dogfood round);
  mid-term is composing them into one supported mode: board in the repo, PRs
  as the merge surface, reviews as the gate.

## Long — exploratory

- **The `.cairn/` format as an open spec.** The end state isn't a bigger
  plugin — it's a small, versioned specification (`meta.json` already carries
  a format stamp) for the board, vault, and protocol files, so any tool can
  read and write a repo's trail. Cairn-the-plugin becomes one implementation;
  Cursor, Codex, and tools that don't exist yet become peers. The handoff
  pack already proves the portability claim; the spec makes it a contract.

## Non-goals (unchanged)

No persistent cloud runtime, no multi-surface bots, no BYOK — see the
Factory-parity section of the [README](./README.md) for the local answer to each.
