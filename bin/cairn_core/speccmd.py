"""`cairn spec` implementation — read board + tickets, write the spec graph.

Kept out of bin/cairn so the CLI entrypoint stays under the 300-line cap. All
.cairn reads/writes go through safepath (dir-fd-anchored: symlinked spec dir or
ticket leaf is refused, not followed outside the repo).
"""
from pathlib import Path

from cairn_core import board, resolve, specgraph, spec_html
from cairn_core.safepath import atomic_write, safe_mkdir, safe_open_read


def _first_heading(text):
    """Return the first markdown heading's text (sans leading #'s), or None."""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            title = s.lstrip("#").strip()
            if title:
                return title
    return None


def _read_ticket(cairn_dir, ticket_id):
    """Best-effort (title, body) for a ticket. Missing/unsafe file -> (None, '').

    Guarded so a missing ticket .md (or a symlinked/raced leaf refused by
    safepath) simply yields no title rather than aborting the whole command.
    """
    path = Path(cairn_dir) / "tickets" / f"{ticket_id}.md"
    try:
        with safe_open_read(cairn_dir, path) as fh:
            body = fh.read()
    except (OSError, ValueError):
        return None, ""
    return _first_heading(body), body


def gather(cairn_dir):
    """Read the board and each ticket file. Return (entries, titles, specs)."""
    entries = board.read_board(cairn_dir)
    titles, specs = {}, {}
    for e in entries:
        tid = e.get("id")
        if not tid:
            continue
        title, body = _read_ticket(cairn_dir, tid)
        if title:
            titles[tid] = title
        if body:
            specs[tid] = body
    return entries, titles, specs


def run(cairn_dir, fmt="both"):
    """Generate the spec graph in the requested format(s). Returns written paths.

    fmt ∈ {mermaid, html, both}. Writes .cairn/spec/graph.mmd and/or graph.html
    via safepath (safe_mkdir for the dir, atomic_write for the files).
    """
    if fmt not in ("mermaid", "html", "both"):
        raise ValueError(f"invalid --format: {fmt} (use mermaid|html|both)")
    entries, titles, specs = gather(cairn_dir)
    # Surface dependency cycles: find_cycle returns the ids on a back-edge cycle
    # (or []), which both generators render as a visible warning. A cycle does not
    # abort the command — the graph is still written so the user can see the loop.
    # include_merged=True: the graph renders ALL tickets/edges regardless of status,
    # so a cycle that passes through a merged ticket must be surfaced too (a merged
    # ticket would otherwise silently break the warning while the loop is still drawn).
    cycle = resolve.find_cycle(entries, include_merged=True)
    spec_dir = Path(cairn_dir) / "spec"
    safe_mkdir(cairn_dir, spec_dir)

    written = []
    if fmt in ("mermaid", "both"):
        mmd = spec_dir / "graph.mmd"
        atomic_write(cairn_dir, mmd,
                     specgraph.to_mermaid(entries, titles=titles, cycle=cycle))
        written.append(mmd)
    if fmt in ("html", "both"):
        html = spec_dir / "graph.html"
        atomic_write(cairn_dir, html,
                     spec_html.to_html(entries, titles=titles, specs=specs,
                                       cycle=cycle))
        written.append(html)
    return written
