---
name: cairn-report
description: Produce a human-readable digest / changelog across all Cairn tickets — what shipped, what's in flight, what's blocked and why — by combining the board with ticket specs and the vault decision/issue logs.
argument-hint: "[--since <ticket-id>]"
---

# cairn-report — human digest & changelog

Synthesize a readable report (NOT just the raw table). Gather:
- `cairn board list` (JSON) for machine state;
- `.cairn/tickets/T##.md` titles/goals for each ticket;
- `.cairn/vault/decisions.md` and `.cairn/vault/issues.md` for rationale and blockers.

Produce three sections:

### Shipped
Merged tickets, newest first: `T## — <title>` + one-line what-changed (from the ticket goal +
any decision logged). This is the changelog.

### In flight
`dispatched`/`in-progress`/`pr-open` tickets with their current branch and what they're waiting
on.

### Blocked
`blocked` tickets with the failure reason from `vault/issues.md` and the suggested remedy.

If `--since T##` is given, restrict "Shipped" to tickets after that id. Read-only — write
nothing to board or vault.
