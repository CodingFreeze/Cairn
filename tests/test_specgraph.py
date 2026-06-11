import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import specgraph


def _entries():
    return [
        {"id": "T01", "status": "merged", "depends_on": []},
        {"id": "T02", "status": "in-progress", "depends_on": ["T01"]},
        {"id": "T03", "status": "todo", "depends_on": ["T02"]},
    ]


def test_mermaid_is_flowchart_td():
    out = specgraph.to_mermaid(_entries())
    assert out.lstrip().startswith("flowchart TD")


def test_mermaid_node_per_ticket():
    out = specgraph.to_mermaid(_entries())
    # one aliased node per ticket; the real id lives inside the escaped label
    for i, tid in enumerate(("T01", "T02", "T03")):
        assert f'n{i}["{tid}' in out


def test_mermaid_edge_per_dependency():
    out = specgraph.to_mermaid(_entries())
    # one edge per dependency, expressed with aliases: n<dep> --> n<id>
    # sorted ids T01,T02,T03 -> n0,n1,n2; T02 dep T01, T03 dep T02
    assert "n0 --> n1" in out
    assert "n1 --> n2" in out
    assert out.count("-->") == 2


def test_mermaid_includes_titles_when_given():
    titles = {"T01": "Schema layer"}
    out = specgraph.to_mermaid(_entries(), titles=titles)
    assert "Schema layer" in out


def test_mermaid_falls_back_to_id_without_title():
    out = specgraph.to_mermaid([{"id": "T09", "status": "todo", "depends_on": []}])
    # alias node identifier, real id inside the label
    assert 'n0["T09' in out


def test_mermaid_has_status_classdefs():
    out = specgraph.to_mermaid(_entries())
    for status in ("merged", "blocked", "in-progress", "todo", "pr-open"):
        assert f"classDef {specgraph._class_name(status)}" in out


def test_mermaid_assigns_node_status_class():
    out = specgraph.to_mermaid(_entries())
    # each node gets a class assignment line, keyed by alias (T01->n0, T03->n2)
    assert f"class n0 {specgraph._class_name('merged')}" in out
    assert f"class n2 {specgraph._class_name('todo')}" in out


def test_mermaid_status_colors_present():
    out = specgraph.to_mermaid(_entries())
    # green for merged, red for blocked etc. encoded as fill colors
    assert "fill:#" in out


def test_mermaid_deterministic_and_sorted():
    shuffled = list(reversed(_entries()))
    assert specgraph.to_mermaid(shuffled) == specgraph.to_mermaid(_entries())
    out = specgraph.to_mermaid(_entries())
    # aliases are assigned in sorted-id order, so n0<n1<n2 nodes appear in order
    assert out.index('n0["') < out.index('n1["') < out.index('n2["')


def test_mermaid_empty_board():
    out = specgraph.to_mermaid([])
    assert out.lstrip().startswith("flowchart TD")
    assert "-->" not in out


def _cyclic_entries():
    return [
        {"id": "T01", "status": "todo", "depends_on": ["T02"]},
        {"id": "T02", "status": "todo", "depends_on": ["T01"]},
    ]


def test_mermaid_no_cycle_warning_without_cycle():
    out = specgraph.to_mermaid(_entries())
    assert "WARNING: dependency cycle" not in out
    assert "cycleWarn" not in out


def test_mermaid_default_output_unchanged_with_cycle_none():
    # backward compatible: omitting cycle (or passing None) is identical
    assert specgraph.to_mermaid(_entries()) == \
        specgraph.to_mermaid(_entries(), cycle=None)


def test_mermaid_surfaces_cycle_warning():
    out = specgraph.to_mermaid(_cyclic_entries(), cycle=["T01", "T02"])
    assert "%% WARNING: dependency cycle among: T01,T02" in out
    # a visible note node carrying the cycle ids
    assert "cycleWarn[" in out
    assert "T01,T02" in out


def test_mermaid_cycle_output_deterministic():
    a = specgraph.to_mermaid(_cyclic_entries(), cycle=["T01", "T02"])
    b = specgraph.to_mermaid(list(reversed(_cyclic_entries())), cycle=["T01", "T02"])
    assert a == b


def test_mermaid_escapes_quotes_and_brackets_in_title():
    entries = [{"id": "T01", "status": "todo", "depends_on": []}]
    titles = {"T01": 'a "quoted" [bracket] title'}
    out = specgraph.to_mermaid(entries, titles=titles)
    # raw unescaped quote/bracket must not appear inside the node label
    assert '"quoted"' not in out
    assert "[bracket]" not in out
    # but the text content survives in an escaped form
    assert "quoted" in out and "bracket" in out


# --- Fix 1 (High): user ticket ids are NEVER emitted as raw Mermaid identifiers.
# Ids allow '-' and '.', so a valid id like "A---B" used as a node/edge identifier
# would be parsed as Mermaid link syntax. Aliases (n0,n1,…) decouple identifiers
# from the real id, which appears ONLY inside the quoted, escaped label. ---

def test_mermaid_uses_index_aliases_not_raw_ids():
    out = specgraph.to_mermaid([{"id": "A---B", "status": "todo", "depends_on": []},
                                {"id": "T01", "status": "todo", "depends_on": []}])
    # node identifiers are aliases, not the raw id
    assert 'n0["' in out and 'n1["' in out
    # the real id is NEVER a bare identifier preceding a label or in edge syntax
    assert "    A---B[" not in out
    # the raw id appears ONLY inside a quoted, escaped label
    for line in out.splitlines():
        if "A---B" in line:
            # the only legitimate occurrence is inside the n<i>["...A---B..."] label
            assert '["' in line and line.rstrip().endswith('"]')
            assert line.lstrip().startswith("n")


def test_mermaid_alias_assignment_is_deterministic_by_sorted_id():
    # ids sorted -> A---B before T01 -> n0 is the A---B node, n1 is T01
    out = specgraph.to_mermaid([{"id": "T01", "status": "todo", "depends_on": []},
                                {"id": "A---B", "status": "todo", "depends_on": []}])
    n0_line = next(l for l in out.splitlines() if l.lstrip().startswith("n0["))
    n1_line = next(l for l in out.splitlines() if l.lstrip().startswith("n1["))
    assert "A---B" in n0_line  # sorts first
    assert "T01" in n1_line


def test_mermaid_edges_use_aliases_not_raw_ids():
    entries = [{"id": "A---B", "status": "merged", "depends_on": []},
               {"id": "T01", "status": "todo", "depends_on": ["A---B"]}]
    out = specgraph.to_mermaid(entries)
    # edge connects aliases (n0 --> n1), never the raw id as link syntax
    assert "n0 --> n1" in out
    # no line where the raw id acts as edge endpoints
    for line in out.splitlines():
        if "-->" in line:
            assert "A---B" not in line


def test_mermaid_class_assignment_uses_aliases():
    out = specgraph.to_mermaid([{"id": "A---B", "status": "merged", "depends_on": []}])
    assert f"class n0 {specgraph._class_name('merged')}" in out
    # no class assignment references the raw id
    for line in out.splitlines():
        if line.lstrip().startswith("class "):
            assert "A---B" not in line


def test_mermaid_alias_output_deterministic():
    entries = [{"id": "A---B", "status": "todo", "depends_on": []},
               {"id": "T01", "status": "todo", "depends_on": ["A---B"]}]
    assert specgraph.to_mermaid(entries) == \
        specgraph.to_mermaid(list(reversed(entries)))
