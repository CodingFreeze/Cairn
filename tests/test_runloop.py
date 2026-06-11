"""Tests for runloop.py — the deterministic reconciler-loop step + run lock."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import board, runloop  # noqa: E402


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo),
                          capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    """Real git repo with one commit on main and a scaffolded .cairn."""
    root = Path(os.path.realpath(tmp_path)) / "repo"
    root.mkdir()
    _git(root, "init", "-q", ".")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "commit", "-q", "--allow-empty", "-m", "init")
    _git(root, "branch", "-M", "main")
    (root / ".cairn").mkdir()
    return root


def test_acquire_refuses_second_fresh_lock(repo):
    d = repo / ".cairn"
    runloop.acquire_lock(d)
    with pytest.raises(ValueError, match="another cairn run"):
        runloop.acquire_lock(d)


def test_acquire_steal_replaces(repo):
    d = repo / ".cairn"
    t1 = runloop.acquire_lock(d)["token"]
    t2 = runloop.acquire_lock(d, steal=True)["token"]
    assert t1 != t2


def test_stale_lock_is_replaceable(repo):
    d = repo / ".cairn"
    runloop.acquire_lock(d)
    # Age the lock past the staleness horizon.
    p = d / runloop.RUN_LOCK
    rec = json.loads(p.read_text())
    rec["ts"] = time.time() - runloop.LOCK_STALE_SECONDS - 10
    p.write_text(json.dumps(rec))
    runloop.acquire_lock(d)  # no raise


def test_release_requires_matching_token(repo):
    d = repo / ".cairn"
    runloop.acquire_lock(d)
    with pytest.raises(ValueError, match="token mismatch"):
        runloop.release_lock(d, "wrong")


def test_release_then_reacquire(repo):
    d = repo / ".cairn"
    tok = runloop.acquire_lock(d)["token"]
    assert runloop.release_lock(d, tok)["released"] is True
    runloop.acquire_lock(d)  # no raise


def test_step_dispatches_ready_ticket(repo):
    d = repo / ".cairn"
    board.add_entry(d, {"id": "T01", "files_owned": ["src/a.py"]})
    out = runloop.step(d, base="main")
    assert out["action"] == "dispatch"
    assert out["id"] == "T01"
    assert out["branch"] == "cairn/T01"
    assert len(out["base_sha"]) == 40
    assert Path(out["worktree"]).is_dir()
    # Board flipped with base_sha + dispatched_at recorded.
    e = board.get_entry(d, "T01")
    assert e["status"] == "dispatched"
    assert e["base_sha"] == out["base_sha"]
    assert "dispatched_at" in e


def test_step_token_enforced(repo):
    d = repo / ".cairn"
    board.add_entry(d, {"id": "T01"})
    runloop.acquire_lock(d)
    with pytest.raises(ValueError, match="token mismatch"):
        runloop.step(d, base="main", token="wrong")


def test_step_includes_ticket_spec(repo):
    d = repo / ".cairn"
    (d / "tickets").mkdir()
    (d / "tickets" / "T01.md").write_text("# Build the thing\nbody\n")
    board.add_entry(d, {"id": "T01"})
    out = runloop.step(d, base="main")
    assert "# Build the thing" in out["spec"]


def test_step_done_when_all_merged(repo):
    d = repo / ".cairn"
    board.add_entry(d, {"id": "T01", "status": "merged"})
    out = runloop.step(d, base="main")
    assert out["action"] == "done"


def test_step_blocked_reports_live_and_cycle(repo):
    d = repo / ".cairn"
    board.add_entry(d, {"id": "T01", "depends_on": ["T02"]})
    board.add_entry(d, {"id": "T02", "depends_on": ["T01"]})
    out = runloop.step(d, base="main")
    assert out["action"] == "blocked"
    assert {e["id"] for e in out["live"]} == {"T01", "T02"}
    assert set(out["cycle"]) == {"T01", "T02"}


def test_step_rejects_dashed_base(repo):
    d = repo / ".cairn"
    board.add_entry(d, {"id": "T01"})
    with pytest.raises(ValueError, match="must not start with '-'"):
        runloop.step(d, base="--evil")


def test_step_rejects_missing_base(repo):
    d = repo / ".cairn"
    board.add_entry(d, {"id": "T01"})
    with pytest.raises(ValueError, match="not an existing local branch"):
        runloop.step(d, base="nope")


def test_step_reuses_existing_branch_worktree(repo):
    """Resume case: branch exists, worktree pruned — step re-adds the worktree."""
    d = repo / ".cairn"
    board.add_entry(d, {"id": "T01"})
    first = runloop.step(d, base="main")
    # Simulate crash cleanup: remove worktree, keep branch, reset board to todo.
    _git(repo, "worktree", "remove", "--force", first["worktree"])
    board.set_fields(d, "T01", {"status": "todo"})
    again = runloop.step(d, base="main")
    assert again["action"] == "dispatch"
    assert again["branch"] == "cairn/T01"
    assert Path(again["worktree"]).is_dir()


def test_step_refuses_worktree_on_wrong_branch(repo):
    d = repo / ".cairn"
    board.add_entry(d, {"id": "T01"})
    wt = d / "worktrees" / "T01"
    _git(repo, "worktree", "add", "-b", "other", str(wt), "main")
    with pytest.raises(ValueError, match="expected 'cairn/T01'"):
        runloop.step(d, base="main")
