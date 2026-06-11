# Cairn Mission Control

A live dashboard for the `.cairn/` control plane: a canvas DAG of the board
(deps + data-contract edges), a reconciler feed, the board table, and the
vault tail — in two modes served by `cairn mission`.

## Demo (replay) mode — the public demo

Open `http://127.0.0.1:4517/` (no query string). The dashboard loads
`mission/demo-events.json`, a pre-authored timeline, and replays a full
plan → dispatch → merge run deterministically. Press **space** to play.
This mode never touches your repo's state.

```sh
cairn mission --no-open     # then open http://127.0.0.1:4517/
```

## Live mode — watch your own board

Open `http://127.0.0.1:4517/?live=1` (the default page `cairn mission`
opens). No timeline: the page polls `GET /api/board` every **1500 ms** and
renders:

- **Graph** — a DAG synthesized from board entries (`depends_on`,
  `produces`, `consumes`, `schema`); board statuses map to node states.
- **Reconciler** — a rolling feed of status *changes* observed between
  polls (`T2: dispatched -> in-progress`, entries added/removed).
- **Board** — the raw `board.jsonl` entries (id / status / branch).
- **Vault** — the last 5 bullets from `vault/decisions.md` and
  `vault/issues.md`.

Drive it from another terminal and watch the panes update:

```sh
cairn board add '{"id": "T1"}'
cairn board set T1 status=in-progress branch=cairn/T1
cairn board set T1 status=merged
```

## Security notes

- **Localhost only.** The server binds `127.0.0.1` exclusively; it is never
  reachable from the network.
- **Read-only API.** Only `GET` is implemented; the dashboard can observe
  the board but never mutate it. Board/vault reads go through the same
  symlink-safe (`safepath`) readers as the CLI.
- **No path traversal.** Static files resolve via `realpath` and must stay
  under `mission/`; `../`, absolute, and percent-encoded attempts get
  403/404. Only an allowlisted set of file suffixes is served.
- **Untrusted rendering.** Ids, branches, statuses, and vault lines come
  from a user repo's `.cairn/` and are treated as hostile: all text is
  HTML-escaped and status values are allowlisted before rendering.
