"""Static CSS for the spec-graph HTML view (the renderer JS lives in
spec_html_js.py; both are split out so each module stays under the 300-line
functional cap). No network, no build — this string is inlined verbatim.

Factory-sober dark palette: near-black canvas, charcoal node cards with hairline
borders, white labels, muted status dots. Colour is RESERVED for the data-contract
layer — a warm accent marks [SCHEMA] tickets, schema-dependency edges, and the
lock-first critical chain. Everything else stays monochrome so the schema spine
reads at a glance even at 16+ nodes.
"""

CSS = """
:root {
  --bg: #0d1117; --grid: #161b22; --card: #1c2128; --card-2: #22272e;
  --line: #30363d; --hair: #21262d; --ink: #e6edf3; --dim: #768390; --mut: #adbac7;
  --accent: #d8915f; --accent-hi: #f0883e; --dep: #424a53;
}
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, "SF Pro Text", Segoe UI, Roboto, Helvetica, sans-serif;
  background: var(--bg); color: var(--ink); height: 100vh; overflow: hidden; }
header { display: flex; align-items: center; gap: 16px; padding: 11px 18px;
  border-bottom: 1px solid var(--hair); background: #0d1117; }
header .brand { font-weight: 650; font-size: 14px; letter-spacing: .2px; }
header .brand .dot { color: var(--accent); }
header .legend { display: flex; gap: 14px; font-size: 11px; color: var(--dim); align-items: center; }
header .legend i { display: inline-block; width: 16px; height: 0; vertical-align: middle;
  margin-right: 5px; border-top-width: 2px; border-top-style: solid; }
header .legend .l-dep i { border-top-color: var(--dep); border-top-style: dashed; }
header .legend .l-schema i { border-top-color: var(--accent); }
header .legend .l-crit i { border-top-color: var(--accent-hi); border-top-width: 2.5px; }
header .spacer { flex: 1; }
#chips { display: flex; gap: 7px; flex-wrap: wrap; }
.chip, #fit, #focus { cursor: pointer; font: 600 11px/1 inherit; letter-spacing: .3px;
  padding: 6px 10px; border-radius: 7px; border: 1px solid var(--line);
  background: transparent; color: var(--dim); transition: .14s; }
.chip { color: var(--c, #768390); border-color: color-mix(in srgb, var(--c, #768390) 45%, transparent); }
.chip:not(.on) { opacity: .4; filter: grayscale(.5); }
#focus.on { color: var(--accent-hi); border-color: var(--accent-hi); background: #f0883e1a; }
#fit:hover, #focus:hover { color: var(--ink); border-color: #475059; }
#graph { width: 100vw; height: calc(100vh - 50px); cursor: grab; display: block;
  background-image: radial-gradient(var(--grid) 1px, transparent 0); background-size: 28px 28px; }
#graph:active { cursor: grabbing; }

.node { cursor: pointer; transition: opacity .15s; }
.node .card { fill: var(--card); stroke: var(--line); stroke-width: 1; }
.node:hover .card { fill: var(--card-2); stroke: #475059; }
.node.schema .card { stroke: color-mix(in srgb, var(--accent) 55%, var(--line)); }
.node.crit .card { stroke: var(--accent-hi); filter: drop-shadow(0 0 4px #f0883e55); }
.schemaBar { fill: var(--accent); }
.node.crit .schemaBar { fill: var(--accent-hi); }
.nid { fill: var(--ink); font-size: 12px; font-weight: 650; }
.ntitle { fill: var(--mut); font-size: 10.5px; }
.badge { fill: var(--accent); font-size: 7.5px; font-weight: 700; letter-spacing: .6px; text-anchor: end; }
.node.crit .badge { fill: var(--accent-hi); }

.edge { fill: none; }
.depEdge { stroke: var(--dep); stroke-width: 1.1; stroke-dasharray: 4 3; }
.schemaEdge { stroke: var(--accent); stroke-width: 1.5; stroke-opacity: .9; }
.critEdge { stroke: var(--accent-hi); stroke-width: 2.2; filter: drop-shadow(0 0 3px #f0883e66); }

#drawer { position: fixed; top: 0; right: 0; width: 408px; height: 100%;
  background: #11151b; border-left: 1px solid var(--line); transform: translateX(100%);
  transition: transform .2s cubic-bezier(.4,0,.2,1); padding: 22px; overflow: auto;
  box-shadow: -24px 0 60px rgba(0,0,0,.5); }
#drawer.open { transform: translateX(0); }
#d-id { font: 800 12px/1 inherit; letter-spacing: 1px; color: var(--accent); margin-bottom: 3px; }
#d-title { margin: 0 0 12px; font-size: 18px; font-weight: 700; }
#d-status, #d-schema { display: inline-block; padding: 4px 9px; border-radius: 999px;
  font: 700 9.5px/1 inherit; letter-spacing: .5px; }
#d-schema { display: none; margin-left: 8px; color: var(--accent); border: 1px solid var(--accent);
  background: #d8915f1a; }
.k { color: var(--dim); font-size: 10.5px; text-transform: uppercase; letter-spacing: .6px; margin: 16px 0 5px; }
#d-produces, #d-consumes, #d-deps { color: var(--ink); font-size: 13px; }
#drawer pre { white-space: pre-wrap; word-wrap: break-word; background: #0d1117;
  border: 1px solid var(--line); border-radius: 9px; padding: 13px; font-size: 12px;
  line-height: 1.5; color: #c9d1d9; }
#d-close { float: right; cursor: pointer; border: 0; background: none; color: var(--dim); font-size: 22px; line-height: 1; }
#d-close:hover { color: var(--ink); }
"""
