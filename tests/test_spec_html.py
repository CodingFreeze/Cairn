import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import spec_html


def _entries():
    return [
        {"id": "T01", "status": "merged", "depends_on": []},
        {"id": "T02", "status": "in-progress", "depends_on": ["T01"]},
        {"id": "T03", "status": "todo", "depends_on": ["T02"]},
    ]


def test_returns_single_html_document():
    out = spec_html.to_html(_entries())
    low = out.lower()
    assert low.lstrip().startswith("<!doctype html")
    assert "</html>" in low
    assert low.count("<html") == 1


def test_contains_every_ticket_id():
    out = spec_html.to_html(_entries())
    for tid in ("T01", "T02", "T03"):
        assert tid in out


def test_embeds_json_data_block():
    out = spec_html.to_html(_entries())
    assert 'id="cairn-spec-data"' in out
    assert 'type="application/json"' in out
    # the embedded JSON references the ids and statuses
    assert '"T01"' in out and '"merged"' in out


def test_no_external_network_dependency():
    out = spec_html.to_html(_entries())
    low = out.lower()
    assert "http://" not in low
    assert "https://" not in low
    assert "cdn" not in low
    # no script with an external src=
    assert not re.search(r'<script[^>]+\bsrc\s*=', low)


def test_contains_svg_and_drawer_markup():
    out = spec_html.to_html(_entries())
    low = out.lower()
    assert "<svg" in low
    assert "drawer" in low
    # interactivity hooks: pan/zoom + click handling present in the JS
    assert "wheel" in low
    assert "mousedown" in low or "pointerdown" in low


def test_includes_spec_text_in_data():
    specs = {"T01": "Define the shared schema here."}
    out = spec_html.to_html(_entries(), specs=specs)
    assert "Define the shared schema here." in out


def test_titles_appear():
    titles = {"T02": "Build the API"}
    out = spec_html.to_html(_entries(), titles=titles)
    assert "Build the API" in out


def test_deterministic_for_fixed_input():
    a = spec_html.to_html(_entries(), titles={"T01": "x"}, specs={"T01": "y"})
    b = spec_html.to_html(_entries(), titles={"T01": "x"}, specs={"T01": "y"})
    assert a == b
    # stable regardless of input ordering
    c = spec_html.to_html(list(reversed(_entries())), titles={"T01": "x"},
                          specs={"T01": "y"})
    assert a == c


def test_escapes_dangerous_data():
    entries = [{"id": "T01", "status": "todo", "depends_on": []}]
    specs = {"T01": "</script><script>alert(1)</script>"}
    out = spec_html.to_html(entries, specs=specs)
    # a raw closing-script breakout must not survive into the embedded data
    assert "</script><script>alert(1)" not in out


def test_empty_board():
    out = spec_html.to_html([])
    assert out.lower().lstrip().startswith("<!doctype html")
    assert "cairn-spec-data" in out


# --- Fix 2 (Medium): surface dependency cycles in the HTML view ---

def _cyclic_entries():
    return [
        {"id": "T01", "status": "todo", "depends_on": ["T02"]},
        {"id": "T02", "status": "todo", "depends_on": ["T01"]},
    ]


def test_html_no_cycle_banner_without_cycle():
    out = spec_html.to_html(_entries())
    assert "Dependency cycle detected" not in out


def test_html_default_output_unchanged_with_cycle_none():
    assert spec_html.to_html(_entries()) == \
        spec_html.to_html(_entries(), cycle=None)


def test_html_renders_cycle_banner():
    out = spec_html.to_html(_cyclic_entries(), cycle=["T01", "T02"])
    assert "Dependency cycle detected" in out
    assert "this DAG is invalid" in out
    assert "T01, T02" in out


def test_html_cycle_banner_escapes_ids():
    out = spec_html.to_html(
        [{"id": "T01", "status": "todo", "depends_on": []}],
        cycle=["<script>"],
    )
    assert "<script>" not in out.split("cairn-spec-data")[0]
    assert "&lt;script&gt;" in out


# --- Fix 1 (High): a real ticket id must NEVER appear as a raw HTML attribute /
# DOM id / unescaped JS identifier — only inside the escaped JSON data island and
# as (runtime) escaped text content. ids carrying Mermaid/HTML metacharacters are
# the adversarial case. (Such ids can exist on a hand-edited board within the
# charset, and the renderer must remain structurally safe regardless.) ---

def test_html_id_with_metachars_only_in_escaped_island():
    # an id with HTML/JS metacharacters: it must not break out of any context.
    weird = 'a"<b>--&'
    out = spec_html.to_html([{"id": weird, "status": "todo", "depends_on": []}])
    # the raw id must NOT appear verbatim anywhere outside the JSON island: the
    # island JSON-escapes < > & and the data is read into the DOM only via
    # setAttribute/textContent at runtime (never interpolated as a raw attribute).
    assert weird not in out
    # the dangerous characters are neutralized in the embedded payload
    island = out.split("cairn-spec-data", 1)[1]
    assert "\\u003c" in island and "\\u003e" in island and "\\u0026" in island
    # no static HTML attribute or DOM id is built from the raw ticket id
    assert f'id="{weird}"' not in out
    assert f'data-id="{weird}"' not in out


def test_html_no_raw_id_in_static_attributes():
    # even ordinary ids appear only in the JSON island + JS textContent, never as
    # a server-rendered DOM id= attribute (which would be index/runtime-driven).
    out = spec_html.to_html(_entries())
    for tid in ("T01", "T02", "T03"):
        assert f'id="{tid}"' not in out
        assert f'data-id="{tid}"' not in out


# --- Fix 1 (High): prototype-pollution — id-keyed JS maps must use
# Object.create(null) or Map so a ticket id like 'constructor' / 'toString' /
# '__proto__' cannot collide with Object.prototype and corrupt layout/edges. ---

def test_js_id_maps_use_null_proto_or_map():
    """The generated JS must not use a bare {} literal as an id-keyed map.

    Any plain `= {}` (with optional whitespace) used as a map that is later
    keyed by ticket id is vulnerable to prototype-pollution for ids like
    'constructor', '__proto__', etc.  The fix must use Object.create(null)
    or new Map(...) for every such map in the embedded JS.
    """
    out = spec_html.to_html(_entries())
    # Extract the <script> block that contains the JS runtime (not the data island).
    # The JS block is the last <script> in the output.
    js_block = out.split("<script>")[-1].split("</script>")[0]
    # There must be NO bare `= {}` (id-keyed map literal) in the JS.
    # Note: `= {}` inside CSS strings or comments don't exist in this file.
    import re as _re
    bare_obj_map = _re.findall(r'=\s*\{\s*\}', js_block)
    assert not bare_obj_map, (
        f"Found bare {{}} id-map literal(s) in JS: {bare_obj_map!r}; "
        "use Object.create(null) or new Map() instead"
    )
    # At least one safe pattern must be present (Object.create(null) or new Map)
    assert "Object.create(null)" in js_block or "new Map(" in js_block, (
        "Expected Object.create(null) or new Map() in JS but found neither"
    )


def test_proto_collision_ids_in_dag():
    """to_html must not raise and must embed proto-collision ids in the data.

    Ticket ids 'constructor', 'toString', '__proto__' are valid per _ID_RE
    (they match [A-Za-z0-9][A-Za-z0-9._-]*) and must be handled without error.
    The data island must contain these ids.
    """
    proto_entries = [
        {"id": "constructor", "status": "todo",        "depends_on": []},
        {"id": "toString",    "status": "in-progress", "depends_on": ["constructor"]},
        {"id": "hasOwnProperty", "status": "merged",   "depends_on": ["constructor"]},
    ]
    # Must not raise
    out = spec_html.to_html(proto_entries)
    # All three ids must appear in the data island (JSON-escaped)
    assert '"constructor"' in out
    assert '"toString"' in out
    assert '"hasOwnProperty"' in out
    # Output must still be a valid HTML document
    assert out.lower().lstrip().startswith("<!doctype html")
    assert "</html>" in out.lower()
