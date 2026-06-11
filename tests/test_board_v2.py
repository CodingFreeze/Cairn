"""Tests for board v2 behaviors: dispatch guard, remove_entry, cancelled status."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402

from cairn_core import board, resolve  # noqa: E402

FIXED = "2026-06-08T00:00:00+00:00"


# --- set_fields dispatch guard: status=dispatched requires base_sha ---

def test_dispatch_without_base_sha_raises(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    with pytest.raises(ValueError, match="base_sha"):
        board.set_fields(tmp_path, "T01", {"status": "dispatched"}, now=FIXED)


def test_dispatch_with_base_sha_in_same_call_succeeds_and_stamps(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    board.set_fields(
        tmp_path, "T01", {"status": "dispatched", "base_sha": "abc123"}, now=FIXED
    )
    e = board.get_entry(tmp_path, "T01")
    assert e["status"] == "dispatched"
    assert e["base_sha"] == "abc123"
    # dispatched_at must be stamped with a parseable ISO timestamp
    assert "dispatched_at" in e
    datetime.fromisoformat(e["dispatched_at"])  # must not raise
    assert e["dispatched_at"] == FIXED


def test_dispatch_with_preexisting_base_sha_succeeds(tmp_path):
    board.add_entry(tmp_path, {"id": "T01", "base_sha": "abc123"}, now=FIXED)
    board.set_fields(tmp_path, "T01", {"status": "dispatched"}, now=FIXED)
    e = board.get_entry(tmp_path, "T01")
    assert e["status"] == "dispatched"
    assert "dispatched_at" in e


# --- remove_entry ---

def test_remove_entry_no_dependents(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    result = board.remove_entry(tmp_path, "T01")
    assert result == {"removed": "T01", "dependents": []}
    assert board.get_entry(tmp_path, "T01") is None


def test_remove_entry_live_dependent_raises(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    board.add_entry(tmp_path, {"id": "T02", "depends_on": ["T01"]}, now=FIXED)
    with pytest.raises(ValueError, match="T02"):
        board.remove_entry(tmp_path, "T01")
    # nothing removed
    assert board.get_entry(tmp_path, "T01") is not None


def test_remove_entry_merged_dependent_ok(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    board.add_entry(
        tmp_path, {"id": "T02", "depends_on": ["T01"], "status": "merged"}, now=FIXED
    )
    result = board.remove_entry(tmp_path, "T01")
    assert result["removed"] == "T01"
    assert result["dependents"] == []


def test_remove_entry_cancelled_dependent_ok(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    board.add_entry(
        tmp_path, {"id": "T02", "depends_on": ["T01"], "status": "cancelled"}, now=FIXED
    )
    result = board.remove_entry(tmp_path, "T01")
    assert result["removed"] == "T01"
    assert result["dependents"] == []


def test_remove_entry_force_removes_despite_live_dependents(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    board.add_entry(tmp_path, {"id": "T02", "depends_on": ["T01"]}, now=FIXED)
    board.add_entry(tmp_path, {"id": "T03", "depends_on": ["T01"]}, now=FIXED)
    result = board.remove_entry(tmp_path, "T01", force=True)
    assert result["removed"] == "T01"
    assert result["dependents"] == ["T02", "T03"]
    assert board.get_entry(tmp_path, "T01") is None
    # dependents themselves stay on the board
    assert board.get_entry(tmp_path, "T02") is not None


def test_remove_entry_unknown_id_raises_keyerror(tmp_path):
    with pytest.raises(KeyError):
        board.remove_entry(tmp_path, "T99")


# --- status 'cancelled' ---

def test_add_entry_accepts_cancelled(tmp_path):
    e = board.add_entry(tmp_path, {"id": "T01", "status": "cancelled"}, now=FIXED)
    assert e["status"] == "cancelled"


def test_set_fields_accepts_cancelled_without_base_sha(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    board.set_fields(tmp_path, "T01", {"status": "cancelled"}, now=FIXED)
    e = board.get_entry(tmp_path, "T01")
    assert e["status"] == "cancelled"
    assert "base_sha" not in e


def _e(id, status="todo", depends_on=None):
    return {"id": id, "status": status, "depends_on": depends_on or []}


def test_next_ready_not_satisfied_by_cancelled_dep():
    entries = [_e("T01", "cancelled"), _e("T02", "todo", ["T01"])]
    assert resolve.next_ready(entries) is None


def test_cancel_impact_returns_transitive_live_dependents_natural_sorted():
    entries = [
        _e("T1"),
        _e("T2", "todo", ["T1"]),
        _e("T10", "todo", ["T2"]),       # transitive via T2
        _e("T3", "merged", ["T1"]),      # merged: not live, excluded
        _e("T4", "cancelled", ["T1"]),   # cancelled: not live, excluded
        _e("T5", "todo", ["T3"]),        # transitive through the merged node
    ]
    impact = resolve.cancel_impact(entries, "T1")
    assert impact == ["T2", "T5", "T10"]  # natural-sorted: T2/T5 before T10


def test_add_entry_dispatched_requires_base_sha(tmp_path):
    with pytest.raises(ValueError, match="base_sha"):
        board.add_entry(tmp_path, {"id": "TX1", "status": "dispatched"})


def test_add_entry_dispatched_with_base_sha_stamps_dispatched_at(tmp_path):
    e = board.add_entry(
        tmp_path, {"id": "TX2", "status": "dispatched", "base_sha": "a" * 40},
        now=FIXED,
    )
    assert e["dispatched_at"] == FIXED
