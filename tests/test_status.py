import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import status


def test_empty_board_message():
    assert status.render([]) == "No tickets on board."


def test_renders_header_and_rows():
    entries = [
        {"id": "T01", "status": "merged", "depends_on": [], "branch": "cairn/T01"},
        {"id": "T02", "status": "todo", "depends_on": ["T01"], "branch": None},
    ]
    out = status.render(entries)
    assert "ID" in out and "STATUS" in out
    assert "T01" in out and "merged" in out
    assert "T02" in out and "T01" in out  # dependency shown
    assert "-" in out  # None branch rendered as dash


def test_rows_sorted_by_id():
    entries = [
        {"id": "T02", "status": "todo", "depends_on": [], "branch": None},
        {"id": "T01", "status": "todo", "depends_on": [], "branch": None},
    ]
    out = status.render(entries)
    assert out.index("T01") < out.index("T02")


def test_render_shows_note_for_missing_deps():
    entries = [
        {"id": "T01", "status": "todo", "depends_on": ["T99"], "branch": None},
    ]
    out = status.render(entries)
    assert "NOTE" in out
    assert "T01" in out
    assert "T99" in out


def test_render_no_note_when_all_deps_present():
    entries = [
        {"id": "T01", "status": "merged", "depends_on": [], "branch": None},
        {"id": "T02", "status": "todo", "depends_on": ["T01"], "branch": None},
    ]
    out = status.render(entries)
    assert "NOTE" not in out


def test_render_shows_cycle_note():
    entries = [
        {"id": "T01", "status": "todo", "depends_on": ["T02"], "branch": None},
        {"id": "T02", "status": "todo", "depends_on": ["T01"], "branch": None},
    ]
    out = status.render(entries)
    assert "dependency cycle detected" in out
    assert "T01" in out and "T02" in out
