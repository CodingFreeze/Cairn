# Spec-graph reference examples

Golden reference for what `cairn spec` should produce. Future Claude Code sessions
working on the Cairn spec graph should open these and **match or exceed** this look —
do not regress to a flat box-and-arrow diagram.

## `driftwatch-reference.html`
The 16-ticket Driftwatch DAG (a Factory AI session, rebuilt in Cairn) rendered by the
v2 generator. Open it directly in a browser. It demonstrates the target aesthetic and
the schema layer:

- **Top-down layered layout** (rank = longest dependency depth), orthogonal elbow edges,
  rank-skipping edges routed to a right-margin lane so the column stays readable at 16+ nodes.
- **Factory-sober dark palette** — charcoal cards, hairline borders, white ids + muted
  titles, dot-grid canvas, muted status dots. Colour is RESERVED for the contract layer.
- **`SCHEMA` badges** on contract-defining tickets (`schema: true` / non-empty `produces`).
- **Schema-dependency edges** (solid accent, producer → consumer of a shared contract) vs
  **plain depends-on** edges (gray dashed).
- **Lock-first schema chain** — the longest path over schema edges, highlighted bright +
  glow, with a "Schema chain" focus toggle that dims everything else.
- Click any node for the drawer (produces / consumes / depends-on / full spec).

Generator: `bin/cairn_core/spec_html.py` + `spec_html_js.py` + `spec_html_assets.py`.
Regenerate any board's graph with `cairn spec --format both` → `.cairn/spec/graph.html`.
