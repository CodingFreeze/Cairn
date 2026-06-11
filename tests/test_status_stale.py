"""Tests for status.render staleness flagging of dispatched tickets."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

from datetime import datetime, timedelta, timezone  # noqa: E402

from cairn_core import status  # noqa: E402

NOW = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


def _dispatched(ts):
    return {
        "id": "T01",
        "status": "dispatched",
        "depends_on": [],
        "branch": "cairn/T01",
        "dispatched_at": ts,
    }


def test_stale_after_three_hours():
    e = _dispatched((NOW - timedelta(hours=3)).isoformat())
    out = status.render([e], now=NOW)
    assert "STALE" in out
    assert "T01" in out


def test_not_stale_after_one_hour():
    e = _dispatched((NOW - timedelta(hours=1)).isoformat())
    out = status.render([e], now=NOW)
    assert "STALE" not in out


def test_malformed_dispatched_at_no_crash_no_stale():
    e = _dispatched("not-a-timestamp")
    out = status.render([e], now=NOW)  # must not raise
    assert "STALE" not in out
    assert "T01" in out  # the row still renders
