import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import resolve


def _e(id, status="todo", depends_on=None):
    return {"id": id, "status": status, "depends_on": depends_on or []}


def test_empty_board_has_no_ready():
    assert resolve.next_ready([]) is None


def test_first_todo_with_no_deps():
    assert resolve.next_ready([_e("T02"), _e("T01")]) == "T01"  # sorted by id


def test_skips_dispatched_and_merged():
    entries = [_e("T01", "merged"), _e("T02", "dispatched"), _e("T03")]
    assert resolve.next_ready(entries) == "T03"


def test_blocks_on_unmet_dependency():
    entries = [_e("T01", "todo"), _e("T02", "todo", ["T01"])]
    assert resolve.next_ready(entries) == "T01"


def test_unblocks_when_dependency_merged():
    entries = [_e("T01", "merged"), _e("T02", "todo", ["T01"])]
    assert resolve.next_ready(entries) == "T02"


def test_dependency_not_merely_dispatched():
    entries = [_e("T01", "dispatched"), _e("T02", "todo", ["T01"])]
    assert resolve.next_ready(entries) is None


def test_all_done_returns_none():
    assert resolve.next_ready([_e("T01", "merged")]) is None


# --- missing_deps tests ---

def test_missing_deps_returns_empty_when_all_present():
    entries = [_e("T01"), _e("T02", depends_on=["T01"])]
    assert resolve.missing_deps(entries) == {}


def test_missing_deps_detects_nonexistent_dep():
    entries = [_e("T01", depends_on=["T99"])]
    result = resolve.missing_deps(entries)
    assert result == {"T01": ["T99"]}


def test_missing_deps_does_not_block_next_ready():
    # T02 depends on missing T99; T01 has no deps and must still be returned
    entries = [_e("T01"), _e("T02", depends_on=["T99"])]
    assert resolve.next_ready(entries) == "T01"
    missing = resolve.missing_deps(entries)
    assert "T02" in missing and "T99" in missing["T02"]


# --- find_cycle tests ---

def test_find_cycle_detects_two_node_cycle():
    entries = [_e("T01", depends_on=["T02"]), _e("T02", depends_on=["T01"])]
    cycle = resolve.find_cycle(entries)
    assert set(cycle) == {"T01", "T02"}


def test_find_cycle_acyclic_returns_empty():
    entries = [_e("T01"), _e("T02", depends_on=["T01"]), _e("T03", depends_on=["T02"])]
    assert resolve.find_cycle(entries) == []


def test_find_cycle_ignores_merged_tickets():
    # A merged ticket breaks the cycle — it is integrated, no longer schedulable.
    entries = [_e("T01", "merged", depends_on=["T02"]), _e("T02", depends_on=["T01"])]
    assert resolve.find_cycle(entries) == []


# --- Fix 2 (Medium): include_merged surfaces cycles through merged tickets ---

def test_find_cycle_merged_cycle_hidden_by_default():
    """Default (include_merged=False) still ignores a merged-involved cycle."""
    entries = [_e("T01", "merged", depends_on=["T02"]), _e("T02", depends_on=["T01"])]
    assert resolve.find_cycle(entries) == []
    assert resolve.find_cycle(entries, include_merged=False) == []


def test_find_cycle_merged_cycle_surfaced_when_included():
    """include_merged=True considers every ticket and returns the cycle ids."""
    entries = [_e("T01", "merged", depends_on=["T02"]), _e("T02", depends_on=["T01"])]
    cycle = resolve.find_cycle(entries, include_merged=True)
    assert set(cycle) == {"T01", "T02"}


def test_find_cycle_include_merged_acyclic_still_empty():
    entries = [_e("T01", "merged"), _e("T02", "merged", depends_on=["T01"])]
    assert resolve.find_cycle(entries, include_merged=True) == []
