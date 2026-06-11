import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import resolve


def _e(id, status="todo", depends_on=None, files_owned=None):
    return {
        "id": id,
        "status": status,
        "depends_on": depends_on or [],
        "files_owned": files_owned or [],
    }


# ---------------------------------------------------------------- ready_all

def test_ready_all_empty_board():
    assert resolve.ready_all([]) == []


def test_ready_all_returns_all_unblocked_todos():
    entries = [_e("T03"), _e("T01"), _e("T02", "merged")]
    assert resolve.ready_all(entries) == ["T01", "T03"]


def test_ready_all_natural_sort_order():
    entries = [_e("T10"), _e("T2"), _e("T1")]
    assert resolve.ready_all(entries) == ["T1", "T2", "T10"]


def test_ready_all_dep_must_be_merged():
    entries = [_e("T01", "dispatched"), _e("T02", depends_on=["T01"]), _e("T03")]
    assert resolve.ready_all(entries) == ["T03"]


def test_ready_all_cancelled_dep_blocks():
    entries = [_e("T01", "cancelled"), _e("T02", depends_on=["T01"])]
    assert resolve.ready_all(entries) == []


def test_ready_all_blocked_dep_blocks():
    entries = [_e("T01", "blocked"), _e("T02", depends_on=["T01"])]
    assert resolve.ready_all(entries) == []


def test_ready_all_merged_dep_satisfies():
    entries = [_e("T01", "merged"), _e("T02", depends_on=["T01"])]
    assert resolve.ready_all(entries) == ["T02"]


def test_ready_all_skips_non_todo_statuses():
    entries = [_e("T01", "merged"), _e("T02", "dispatched"), _e("T03", "blocked")]
    assert resolve.ready_all(entries) == []


# ------------------------------------------------------------ parallel_safe

def test_parallel_safe_empty():
    assert resolve.parallel_safe([], []) == []


def test_parallel_safe_disjoint_sets_all_pass():
    entries = [
        _e("T01", files_owned=["a.py"]),
        _e("T02", files_owned=["b.py"]),
        _e("T03", files_owned=["c/d.py"]),
    ]
    assert resolve.parallel_safe(entries, ["T01", "T02", "T03"]) == [
        "T01", "T02", "T03"]


def test_parallel_safe_overlap_drops_later_ticket():
    entries = [
        _e("T01", files_owned=["a.py", "b.py"]),
        _e("T02", files_owned=["b.py"]),
        _e("T03", files_owned=["c.py"]),
    ]
    assert resolve.parallel_safe(entries, ["T01", "T02", "T03"]) == ["T01", "T03"]


def test_parallel_safe_dir_prefix_conflicts():
    entries = [
        _e("T01", files_owned=["src/"]),
        _e("T02", files_owned=["src/a.py"]),
    ]
    assert resolve.parallel_safe(entries, ["T01", "T02"]) == ["T01"]


def test_parallel_safe_dir_prefix_conflicts_reversed():
    entries = [
        _e("T01", files_owned=["src/a.py"]),
        _e("T02", files_owned=["src"]),
    ]
    assert resolve.parallel_safe(entries, ["T01", "T02"]) == ["T01"]


def test_parallel_safe_prefix_is_path_aware_not_string():
    # "src" vs "srcfoo.py" share a string prefix but are NOT a path conflict.
    entries = [
        _e("T01", files_owned=["src"]),
        _e("T02", files_owned=["srcfoo.py"]),
    ]
    assert resolve.parallel_safe(entries, ["T01", "T02"]) == ["T01", "T02"]


def test_parallel_safe_empty_files_first_runs_alone():
    entries = [
        _e("T01"),  # empty files_owned: could touch anything
        _e("T02", files_owned=["b.py"]),
    ]
    assert resolve.parallel_safe(entries, ["T01", "T02"]) == ["T01"]


def test_parallel_safe_empty_files_non_first_excluded():
    entries = [
        _e("T01", files_owned=["a.py"]),
        _e("T02"),  # wildcard, but not first pick
        _e("T03", files_owned=["c.py"]),
    ]
    assert resolve.parallel_safe(entries, ["T01", "T02", "T03"]) == ["T01", "T03"]


def test_parallel_safe_greedy_order_deterministic():
    # Greedy by natural_key regardless of input ordering of ready_ids.
    entries = [
        _e("T2", files_owned=["x.py"]),
        _e("T10", files_owned=["y.py"]),
        _e("T1", files_owned=["x.py"]),
    ]
    assert resolve.parallel_safe(entries, ["T10", "T2", "T1"]) == ["T1", "T10"]
    assert resolve.parallel_safe(entries, ["T1", "T2", "T10"]) == ["T1", "T10"]
