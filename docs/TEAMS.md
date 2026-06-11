# Teams — cairn in multiplayer

Cairn's memory lives in git, so multiplayer is not a feature bolted on top —
it is what git already does, plus three rules. This page is the whole story:
clone = inherit the brain, union-merge for the journals, single writer for the
board, and `cairn board doctor` for the messy cases.

## Clone = inherit the brain

Everything cairn knows is plain files under `.cairn/`, committed alongside the
code. When a teammate clones the repo they inherit the entire project brain at
the same commit as the code itself:

- `vault/` — decisions, issues, schema notes, the map (append-only journals)
- `handoff/` — resume packs for the next session
- `board.jsonl` — the ticket control plane
- `spec/` — the rendered plan

No sync service, no export step, no onboarding doc that drifts. `git clone`,
then `cairn status` — the new teammate is looking at the same brain you are,
versioned at the same point in history.

## Union merge: the vault never conflicts

`cairn init` scaffolds `.cairn/.gitattributes` (marker-fenced, additive —
your own rules are never clobbered) with:

```
vault/*.md  merge=union
handoff/*.md merge=union
```

Vault and handoff files are **append-only journals**: every entry is a new
timestamped bullet, and `cairn vault append` never rewrites prior content.
When two clones each append entries and the branches merge, the only honest
resolution is "keep both" — which is exactly what git's `union` merge driver
does. Two people capturing decisions in parallel produce zero conflicts; the
merged journal simply contains both sides' entries.

### Why `board.jsonl` is deliberately NOT union

The board is the opposite kind of file: **last-write-wins state**, not a
journal. Each line is the current state of one ticket. If git union-merged it,
two clones that both touched ticket `T01` would merge into a board with *two*
`T01` lines — and `read_board` fails closed on duplicate ids (a duplicate
`T01` marked `merged` could wrongly unblock dependents while the real `T01`
is still in flight). A union merge here would silently manufacture exactly
the corruption the read side is designed to reject.

So board conflicts are left to surface as **real git conflicts**. You resolve
them like code — or you let the merge land messily and run
`cairn board doctor` (below). Loud and repairable beats silent and corrupt.

## The board single-writer rule

Within one clone, `cairn run` serializes conductors with a run-lock
(`cairn run-lock acquire`). But the run-lock is a *per-clone* file lock — it
cannot see a conductor in someone else's clone. Across a team, the
serialization point is the **base branch**:

- **One conductor at a time** mutates the board for a given base branch.
- Board mutations reach teammates the same way code does: **merges land via
  PRs into the base branch**. The base branch's linear history is what makes
  concurrent board edits impossible — two PRs that both touch `board.jsonl`
  cannot both land cleanly, so the second one rebases and reconciles.
- Workers in worktrees never write the shared board directly; they report,
  and the conductor records.

Treat "who is running the conductor" like "who has the deploy stick": exactly
one at a time, handed off explicitly, with the base branch as the referee.

## `cairn board doctor` — the messy cases

When a team merge does damage the board anyway (a mis-resolved conflict, a
`git merge` driven past the markers, a hand edit), `read_board` fails closed
and every board command stops. `cairn board doctor` is the repair tool for
the two states a team merge can produce:

1. **Duplicate ticket ids** — both sides' lines for the same ticket survived
   the merge. Doctor keeps the newest by `updated` (ties keep the later line)
   and reports every line it would drop.
2. **Malformed lines** — conflict-marker debris, truncated JSON, or entries
   failing read-side validation. Doctor reports them and quarantines the raw
   lines to `.cairn/board.jsonl.rej` (append-only, timestamped header per
   run) so nothing is ever silently destroyed.

```sh
cairn board doctor          # dry-run: diagnose and print, write nothing
cairn board doctor --apply  # repair: atomic rewrite + quarantine to .rej
```

Dry-run is the default; `--apply` rewrites the board atomically (under the
board lock) and never clobbers a previous quarantine. After an `--apply`,
review `board.jsonl.rej`, salvage anything real with `cairn board add` /
`cairn board set`, and commit the repaired board like any other change.

## The loop, end to end

1. Teammate clones → inherits the brain.
2. Everyone appends to the vault freely — union merge keeps all of it.
3. One conductor per base branch runs the board; board changes land via PRs.
4. If a merge still mangles the board: `cairn board doctor --apply`, review
   the `.rej`, commit, continue.
