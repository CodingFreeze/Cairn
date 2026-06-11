"""Ticket-id charset validation — prevents path traversal via .cairn/worktrees/<id>."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import board

FIXED = "2026-06-08T00:00:00+00:00"


def test_add_entry_rejects_slash_id(tmp_path):
    with pytest.raises(ValueError):
        board.add_entry(tmp_path, {"id": "A/B"}, now=FIXED)


def test_add_entry_rejects_dotdot_id(tmp_path):
    with pytest.raises(ValueError):
        board.add_entry(tmp_path, {"id": "..", "status": "todo"}, now=FIXED)
    with pytest.raises(ValueError):
        board.add_entry(tmp_path, {"id": "a..b"}, now=FIXED)


def test_add_entry_rejects_leading_dash_id(tmp_path):
    with pytest.raises(ValueError):
        board.add_entry(tmp_path, {"id": "-x"}, now=FIXED)


def test_add_entry_rejects_leading_dot_id(tmp_path):
    with pytest.raises(ValueError):
        board.add_entry(tmp_path, {"id": ".hidden"}, now=FIXED)


def test_add_entry_accepts_normal_ids(tmp_path):
    for good in ["T01", "feat-1", "a.b", "T01_v2"]:
        board.add_entry(tmp_path, {"id": good}, now=FIXED)
        assert board.get_entry(tmp_path, good)["id"] == good


# --- Fix 1: read_board validates ticket ids (fail-closed on malicious board.jsonl) ---

def test_read_board_rejects_dotdot_id(tmp_path):
    """A hand-edited board.jsonl with id '../escape' must raise ValueError on read."""
    p = tmp_path / "board.jsonl"
    p.write_text('{"id": "../escape", "status": "todo", "depends_on": []}\n')
    with pytest.raises(ValueError, match="invalid ticket id"):
        board.read_board(tmp_path)


def test_read_board_rejects_slash_id(tmp_path):
    """A hand-edited board.jsonl with id 'a/b' must raise ValueError on read."""
    p = tmp_path / "board.jsonl"
    p.write_text('{"id": "a/b", "status": "todo", "depends_on": []}\n')
    with pytest.raises(ValueError, match="invalid ticket id"):
        board.read_board(tmp_path)


def test_read_board_valid_ids_pass(tmp_path):
    """A board with only valid ids reads without error."""
    p = tmp_path / "board.jsonl"
    p.write_text(
        '{"id": "T01", "status": "todo", "depends_on": []}\n'
        '{"id": "feat-2", "status": "in-progress", "depends_on": []}\n'
    )
    entries = board.read_board(tmp_path)
    assert len(entries) == 2
    assert entries[0]["id"] == "T01"
    assert entries[1]["id"] == "feat-2"


# --- Fix 2: read_board rejects duplicate ticket ids (fail-closed) ---

def test_read_board_rejects_duplicate_ids(tmp_path):
    """A hand-edited board.jsonl with two 'T01' lines must raise ValueError.

    Without this guard resolve.next_ready collapses duplicates last-write-wins, so
    a duplicate T01 marked 'merged' could wrongly unblock dependents while the real
    T01 is still todo/blocked. Fail closed on read."""
    p = tmp_path / "board.jsonl"
    p.write_text(
        '{"id": "T01", "status": "todo", "depends_on": []}\n'
        '{"id": "T01", "status": "merged", "depends_on": []}\n'
    )
    with pytest.raises(ValueError, match="duplicate ticket id"):
        board.read_board(tmp_path)


def test_read_board_unique_ids_ok(tmp_path):
    """A board with all-unique ids reads fine (no false positive)."""
    p = tmp_path / "board.jsonl"
    p.write_text(
        '{"id": "T01", "status": "todo", "depends_on": []}\n'
        '{"id": "T02", "status": "merged", "depends_on": []}\n'
        '{"id": "T03", "status": "blocked", "depends_on": []}\n'
    )
    entries = board.read_board(tmp_path)
    assert [e["id"] for e in entries] == ["T01", "T02", "T03"]


def test_add_entry_rejects_trailing_newline_id(tmp_path):
    for bad in ["T01\n", "T01\nX", "\nT01"]:
        with pytest.raises(ValueError):
            board.add_entry(tmp_path, {"id": bad}, now=FIXED)


# --- Fix 1 (High): depends_on items are ticket-id references, not free strings.
# Each is emitted into Mermaid edge syntax (dep --> id), so a newline / '-->' /
# directive in a depends_on value can break out of the edge context. Validate
# every depends_on item with the SAME id rules, on BOTH the write and read paths. ---

@pytest.mark.parametrize("bad", [["a\nb"], ["x-->y"], ["../e"], ["a/b"], ["-x"]])
def test_add_entry_rejects_malformed_depends_on(tmp_path, bad):
    with pytest.raises(ValueError, match="invalid depends_on id"):
        board.add_entry(tmp_path, {"id": "T01", "depends_on": bad}, now=FIXED)


def test_add_entry_accepts_valid_depends_on(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    board.add_entry(tmp_path, {"id": "feat-2"}, now=FIXED)
    e = board.add_entry(
        tmp_path, {"id": "T03", "depends_on": ["T01", "feat-2"]}, now=FIXED
    )
    assert e["depends_on"] == ["T01", "feat-2"]


def test_set_fields_rejects_malformed_depends_on(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    with pytest.raises(ValueError, match="invalid depends_on id"):
        board.set_fields(tmp_path, "T01", {"depends_on": ["a-->b"]}, now=FIXED)


def test_read_board_rejects_malformed_depends_on(tmp_path):
    """A hand-written board.jsonl whose depends_on contains 'a\\nb' must raise."""
    p = tmp_path / "board.jsonl"
    p.write_text('{"id": "T01", "status": "todo", "depends_on": ["a\\nb"]}\n')
    with pytest.raises(ValueError, match="invalid depends_on id"):
        board.read_board(tmp_path)


def test_read_board_accepts_valid_depends_on(tmp_path):
    p = tmp_path / "board.jsonl"
    p.write_text(
        '{"id": "T01", "status": "merged", "depends_on": []}\n'
        '{"id": "T02", "status": "todo", "depends_on": ["T01"]}\n'
    )
    entries = board.read_board(tmp_path)
    assert entries[1]["depends_on"] == ["T01"]


# --- Fix 3 (data-integrity): read_board fails closed on a non-list depends_on.
# `.get("depends_on") or []` silently coerced null/0/"" to [], dropping edges from
# a hand-edited board. A non-list value must now raise, not be swallowed. ---

@pytest.mark.parametrize("bad", ['"T01"', "null", "0", "false", "{}"])
def test_read_board_rejects_non_list_depends_on(tmp_path, bad):
    p = tmp_path / "board.jsonl"
    p.write_text('{"id": "T01", "status": "todo", "depends_on": %s}\n' % bad)
    with pytest.raises(ValueError, match="depends_on must be a list for T01"):
        board.read_board(tmp_path)


def test_read_board_absent_depends_on_defaults_empty(tmp_path):
    """Absent depends_on key still reads fine (defaults to [])."""
    p = tmp_path / "board.jsonl"
    p.write_text('{"id": "T01", "status": "todo"}\n')
    entries = board.read_board(tmp_path)
    assert entries[0].get("depends_on", []) == []


def test_files_owned_not_id_validated(tmp_path):
    """files_owned are paths, not ids — slashes must stay allowed."""
    e = board.add_entry(
        tmp_path, {"id": "T01", "files_owned": ["src/a/b.py", "../x"]}, now=FIXED
    )
    assert e["files_owned"] == ["src/a/b.py", "../x"]


# --- Fix 2 (Medium): read_board must validate status at read-time ---
# A hand-edited board.jsonl can set status to a JSON object, list, number, or
# unknown string. _STATUS_STYLE.get(status, default) raises TypeError on an
# unhashable value (dict/list); an unknown string silently mis-styles. Validate
# fail-closed at read time, consistent with existing id/depends_on validation.

@pytest.mark.parametrize("bad_status", [
    '{}',       # dict — unhashable, TypeError in get()
    '["x"]',    # list — unhashable, TypeError in get()
    '5',        # int — silently mis-styles and breaks typed consumers
])
def test_read_board_rejects_non_string_status(tmp_path, bad_status):
    """Hand-edited status that is not a string must raise ValueError on read."""
    p = tmp_path / "board.jsonl"
    p.write_text(
        '{"id": "T01", "status": %s, "depends_on": []}\n' % bad_status
    )
    with pytest.raises(ValueError, match="invalid status"):
        board.read_board(tmp_path)


def test_read_board_rejects_unknown_string_status(tmp_path):
    """Unknown status string must raise ValueError — fail-closed, not silent mis-style."""
    p = tmp_path / "board.jsonl"
    p.write_text('{"id": "T01", "status": "bogus", "depends_on": []}\n')
    with pytest.raises(ValueError, match="invalid status"):
        board.read_board(tmp_path)


def test_read_board_accepts_all_valid_statuses(tmp_path):
    """A board with all valid statuses reads without error."""
    lines = "\n".join(
        '{"id": "%s", "status": "%s", "depends_on": []}' % (f"T{i:02d}", s)
        for i, s in enumerate(sorted(board.VALID_STATUS))
    ) + "\n"
    p = tmp_path / "board.jsonl"
    p.write_text(lines)
    entries = board.read_board(tmp_path)
    assert len(entries) == len(board.VALID_STATUS)


def test_read_board_rejects_explicit_null_status(tmp_path):
    cairn = tmp_path / ".cairn"
    cairn.mkdir()
    (cairn / "board.jsonl").write_text(
        '{"id": "T01", "status": null, "depends_on": []}\n'
    )
    with pytest.raises(ValueError):
        board.read_board(cairn)
