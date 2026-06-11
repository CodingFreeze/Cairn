"""Pure Mermaid generator for the spec graph (stdlib only, deterministic).

Renders a board (list of ticket entries) as a Mermaid `flowchart TD`:
one node per ticket, one edge per dependency, status-colored classDefs.
No I/O, no clock, no randomness — same input always yields the same string.
The interactive HTML view lives in spec_html.py to keep both files small.
"""
import re

# status -> (mermaid class name, fill color). Amber for active work, green for
# merged, red for blocked, blue for pr-open, gray for todo/unknown.
_STATUS_STYLE = {
    "merged": ("stMerged", "#1a7f37", "#d2f4d8"),
    "blocked": ("stBlocked", "#cf222e", "#ffd7d5"),
    "in-progress": ("stProgress", "#bf8700", "#fff8c5"),
    "dispatched": ("stProgress", "#bf8700", "#fff8c5"),
    "pr-open": ("stPrOpen", "#0969da", "#ddf4ff"),
    "todo": ("stTodo", "#57606a", "#eaeef2"),
}
_DEFAULT_STYLE = ("stTodo", "#57606a", "#eaeef2")


def _class_name(status):
    """Mermaid classDef name for a status (falls back to the todo/gray class)."""
    return _STATUS_STYLE.get(status, _DEFAULT_STYLE)[0]


def _escape_label(text):
    """Make `text` safe inside a Mermaid `"..."` node label.

    Mermaid breaks on raw double-quotes and square brackets in labels. Replace
    quotes with the typographic equivalent and brackets with parens so the label
    stays single-token and readable.
    """
    return (
        str(text)
        .replace("\\", "/")
        .replace('"', "'")
        .replace("[", "(")
        .replace("]", ")")
        .replace("\n", " ")
        .replace("\r", " ")
        .strip()
    )


def _label(entry, titles):
    tid = entry["id"]
    title = (titles or {}).get(tid)
    status = entry.get("status", "todo")
    # "SCHEMA ·" marks a contract-defining ticket (parity with the HTML badge).
    # No literal square brackets — Mermaid treats "[" / "]" as node syntax.
    schema = bool(entry.get("schema")) or bool(entry.get("produces"))
    flag = "SCHEMA · " if schema else ""
    if title:
        t = _escape_label(title)
        # strip a leading "<id>" + optional separator so the id is not shown twice
        t = re.sub(r"^" + re.escape(tid) + r"\s*[—:\-]?\s*", "", t) or tid
        body = f"{tid} — {t}"
    else:
        body = tid
    return f"{flag}{body} · {_escape_label(status)}"


def to_mermaid(entries, titles=None, cycle=None):
    """Return a deterministic Mermaid `flowchart TD` for the given board entries.

    - one node `T01["T01: <title> · <status>"]` per ticket (id fallback),
    - one `dep --> id` edge per entry in depends_on,
    - status classDefs + a class assignment per node.
    Entries are sorted by id so output is stable regardless of input order.

    If `cycle` (a list of ticket ids from resolve.find_cycle) is non-empty, the
    DAG is invalid: prepend a visible `%% WARNING` comment and add a red note
    node so the broken cycle is obvious in the rendered diagram. Defaulting
    cycle to None keeps prior output byte-for-byte identical (backward compatible).
    """
    ordered = sorted(entries, key=lambda e: str(e.get("id", "")))
    # SECURITY/CORRECTNESS: never use a user ticket id as a Mermaid identifier. Ids
    # allow '-' and '.', so a valid id like "A---B" used as a node/edge identifier
    # would be parsed as link syntax and corrupt the graph. Assign a deterministic
    # index alias (n0,n1,…) per sorted id; the real id appears ONLY inside the
    # quoted, escaped label. Edges/classes reference aliases, never raw ids.
    alias = {str(e.get("id", "")): f"n{i}" for i, e in enumerate(ordered)}
    cycle_ids = ",".join(cycle) if cycle else ""
    lines = []
    if cycle_ids:
        lines.append(f"%% WARNING: dependency cycle among: {cycle_ids}")
    lines.append("flowchart TD")
    if cycle_ids:
        # cycleWarn is a fixed literal alias; the real ids appear only as escaped
        # label text, never as Mermaid identifiers.
        lines.append(f'    cycleWarn["⚠ CYCLE: {_escape_label(cycle_ids)}"]')

    # Nodes (aliased identifier, real id only inside the escaped label).
    for e in ordered:
        lines.append(f'    {alias[str(e["id"])]}["{_label(e, titles)}"]')

    # Edges (one per dependency, sorted for determinism). Both endpoints are
    # aliases. A dep that is not a known node has no alias — skip it (it would
    # otherwise reintroduce a raw id as an edge endpoint).
    for e in ordered:
        dst = alias[str(e["id"])]
        for dep in sorted(e.get("depends_on") or []):
            src = alias.get(str(dep))
            if src is not None:
                lines.append(f"    {src} --> {dst}")

    # classDefs (stable order from a fixed list of distinct styles).
    seen = []
    for style in list(_STATUS_STYLE.values()) + [_DEFAULT_STYLE]:
        name, stroke, fill = style
        if name in seen:
            continue
        seen.append(name)
        lines.append(
            f"    classDef {name} fill:{fill},stroke:{stroke},"
            f"color:#1f2328,stroke-width:1px;"
        )

    # class assignments per node (keyed by alias, never the raw id).
    for e in ordered:
        cls = _class_name(e.get("status", "todo"))
        lines.append(f"    class {alias[str(e['id'])]} {cls}")

    # Distinct red style for the cycle warning note node (appended last so the
    # acyclic output above is unchanged when there is no cycle).
    if cycle_ids:
        lines.append(
            "    classDef stCycle fill:#ffd7d5,stroke:#cf222e,"
            "color:#1f2328,stroke-width:2px;"
        )
        lines.append("    class cycleWarn stCycle")

    return "\n".join(lines) + "\n"
