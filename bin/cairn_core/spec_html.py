"""Self-contained interactive HTML spec-graph view (stdlib only, deterministic).

`to_html(entries, titles, specs)` returns ONE portable HTML document: the ticket
data is embedded as a JSON `<script type="application/json">` block, and a small
vanilla-JS layered-DAG renderer draws nodes/edges as inline SVG with pan, zoom, a
critical-path spine highlight, status filter chips, and a click-to-open spec
drawer. No CDN, no network, no build step — open the .html and it works. Same
input always yields the same bytes (no Date/random).

The JS + CSS live in `spec_html_assets` (keeps this module under the line cap and
escaping in one place). Visual language borrows from idea-map-builder (column
clusters, color-coded edges, deep-detail drawer) in a dark "sunburst" palette:
coral -> gold -> lime -> teal -> sky across dependency depth.
"""
import html
import json

from cairn_core.specgraph import _STATUS_STYLE, _DEFAULT_STYLE
from cairn_core.spec_html_assets import CSS as _CSS
from cairn_core.spec_html_js import JS as _JS


def _style_for(status):
    s = _STATUS_STYLE.get(status, _DEFAULT_STYLE)
    return {"stroke": s[1], "fill": s[2]}


def _node_payload(entries, titles, specs):
    titles = titles or {}
    specs = specs or {}
    out = []
    for e in sorted(entries, key=lambda x: str(x.get("id", ""))):
        tid = e["id"]
        status = e.get("status", "todo")
        out.append({
            "id": tid,
            "status": status,
            "depends_on": sorted(e.get("depends_on") or []),
            "title": str(titles.get(tid, "")),
            "spec": str(specs.get(tid, "")),
            "style": _style_for(status),
            # data-contract model (drives [SCHEMA] badges + schema-dependency edges)
            "schema": bool(e.get("schema", False)),
            "produces": sorted(e.get("produces") or []),
            "consumes": sorted(e.get("consumes") or []),
        })
    return out


def _embed_json(data):
    """JSON-encode for safe embedding inside a <script> island.

    json.dumps with ensure_ascii escapes non-ASCII; we additionally neutralize
    the `<`/`>`/`&` characters so a payload containing `</script>` (or an HTML
    entity) cannot break out of the script element.
    """
    raw = json.dumps(data, ensure_ascii=True, sort_keys=True)
    return (raw.replace("<", "\\u003c").replace(">", "\\u003e")
               .replace("&", "\\u0026"))


def _cycle_banner(cycle):
    """Visible red banner naming the cycle ids, or '' when there is no cycle.

    The JS layering already terminates on cycles (the `seen` guard returns 0),
    which silently hid them; this surfaces the invalid DAG to the viewer. Ids are
    HTML-escaped so a crafted id cannot inject markup into the banner.
    """
    if not cycle:
        return ""
    ids = ", ".join(html.escape(str(c)) for c in cycle)
    return (
        '<div id="cycle-banner" role="alert" style="background:#3d1418;'
        "color:#ff9492;border-bottom:1px solid #f85149;padding:12px 16px;"
        'font-weight:600;">⚠ Dependency cycle detected: '
        f"{ids} — this DAG is invalid</div>"
    )


def to_html(entries, titles=None, specs=None, cycle=None):
    """Return a single self-contained interactive HTML spec graph (deterministic).

    `cycle` (a list of ids from resolve.find_cycle) defaults to None: when empty
    no banner is rendered; when non-empty a red banner naming the cycle ids is
    rendered at the top.
    """
    data = _node_payload(entries or [], titles, specs)
    payload = _embed_json(data)
    banner = _cycle_banner(cycle)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cairn spec graph</title>
<style>{_CSS}</style>
</head>
<body>
{banner}<header>
  <span class="brand">Cairn <span class="dot">●</span> spec graph</span>
  <span class="legend">
    <span class="l-dep"><i></i>depends-on</span>
    <span class="l-schema"><i></i>schema dep</span>
    <span class="l-crit"><i></i>lock-first chain</span>
  </span>
  <span class="spacer"></span>
  <div id="chips"></div>
  <button id="focus">Schema chain</button>
  <button id="fit">Fit</button>
</header>
<svg id="graph">
<defs>
<marker id="arrowD" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6.5"
  markerHeight="6.5" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#424a53"></path></marker>
<marker id="arrowS" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
  markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#d8915f"></path></marker>
<marker id="arrowC" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7.5"
  markerHeight="7.5" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#f0883e"></path></marker>
</defs>
</svg>
<aside id="drawer">
<button id="d-close" aria-label="close">&times;</button>
<div id="d-id">—</div>
<h2 id="d-title"></h2>
<span id="d-status"></span><span id="d-schema">SCHEMA</span>
<div class="k">Produces (contracts)</div><div id="d-produces"></div>
<div class="k">Consumes (contracts)</div><div id="d-consumes"></div>
<div class="k">Depends on</div><div id="d-deps"></div>
<div class="k">Spec</div><pre id="d-spec"></pre>
</aside>
<script id="cairn-spec-data" type="application/json">{payload}</script>
<script>{_JS}</script>
</body>
</html>
"""
