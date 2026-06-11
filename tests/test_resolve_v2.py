"""Tests for resolve.natural_key / next_ready natural-sort ordering."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

from cairn_core import resolve  # noqa: E402


def _e(id, status="todo", depends_on=None):
    return {"id": id, "status": status, "depends_on": depends_on or []}


def test_natural_key_orders_t2_before_t10():
    assert resolve.natural_key("T2") < resolve.natural_key("T10")
    # plain lexicographic would have it the other way around
    assert sorted(["T10", "T2"], key=resolve.natural_key) == ["T2", "T10"]


def test_next_ready_returns_t2_over_t10():
    entries = [_e("T10"), _e("T2")]
    assert resolve.next_ready(entries) == "T2"


def test_next_ready_mixed_merged_and_unpadded():
    entries = [_e("T1", "merged"), _e("T11"), _e("T10"), _e("T9")]
    assert resolve.next_ready(entries) == "T9"
