"""Mergeflow v2 tests: detached HEAD, out-of-scope sweep warning, ticket-title commits.

Builds real throwaway git repos (same pattern as test_mergeflow.py). tmp_path is
realpath-resolved because the macOS /tmp symlink breaks safepath root checks.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import pytest  # noqa: E402

from cairn_core import mergeflow  # noqa: E402

CLI = Path(__file__).resolve().parent.parent / "bin" / "cairn"


def _git(args, cwd):
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)} failed: {r.stderr}"
    return r.stdout.strip()


def _cli(args, cwd):
    return subprocess.run(
        [sys.executable, str(CLI), *args], cwd=str(cwd), capture_output=True, text=True
    )


def _repo(tmp_path, goal="demo"):
    _git(["init"], tmp_path)
    _git(["config", "user.email", "t@t.co"], tmp_path)
    _git(["config", "user.name", "tester"], tmp_path)
    _cli(["init", ".", "--goal", goal], tmp_path)
    (tmp_path / "app.txt").write_text("v1\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-m", "baseline"], tmp_path)


def _dispatch(tmp_path, tid, files_owned=None):
    base_sha = _git(["rev-parse", "main"], tmp_path)
    entry = {"id": tid, "goal": f"{tid} work", "status": "dispatched",
             "branch": f"cairn/{tid}", "depends_on": [], "base_sha": base_sha}
    if files_owned is not None:
        entry["files_owned"] = files_owned
    r = _cli(["board", "add", json.dumps(entry)], tmp_path)
    assert r.returncode == 0, r.stderr
    _git(["worktree", "add", "-b", f"cairn/{tid}", f".cairn/worktrees/{tid}", "main"],
         tmp_path)


@pytest.fixture
def repo(tmp_path):
    # macOS pytest tmp dirs can sit behind the /tmp -> /private/tmp symlink,
    # which trips safepath's realpath-based root checks — resolve it up front.
    p = Path(os.path.realpath(tmp_path))
    _repo(p)
    return p


def test_merge_detached_head_raises(repo):
    """A detached-HEAD worktree must be refused before any mutation."""
    _dispatch(repo, "T01")
    wt = repo / ".cairn" / "worktrees" / "T01"
    _git(["checkout", "--detach"], wt)

    with pytest.raises(ValueError, match="detached"):
        mergeflow.run(repo / ".cairn", "T01")

    # nothing mutated: worktree intact
    assert wt.exists()


def test_merge_dirty_outside_files_owned_warns(repo):
    """Dirty path outside files_owned: merge still succeeds (fix-forward, work is
    never dropped) but the summary names the out-of-scope path in a WARNING."""
    _dispatch(repo, "T01", files_owned=["src/"])
    wt = repo / ".cairn" / "worktrees" / "T01"
    (wt / "src").mkdir()
    (wt / "src" / "mod.txt").write_text("in scope\n")
    (wt / "stray.txt").write_text("out of scope\n")

    summary = mergeflow.run(repo / ".cairn", "T01")
    assert summary.startswith("OK T01"), summary
    assert "WARNING" in summary
    assert "stray.txt" in summary
    # the in-scope path is not flagged
    assert "src/mod.txt" not in summary
    # both files still landed on main — nothing was dropped
    assert (repo / "stray.txt").exists()
    assert (repo / "src" / "mod.txt").exists()


def test_sweep_commit_uses_ticket_title(repo):
    """The sweep commit message takes its goal from the '# ' title line of
    .cairn/tickets/<tid>.md, not the bare ticket id."""
    _dispatch(repo, "T01")
    (repo / ".cairn" / "tickets" / "T01.md").write_text(
        "# My title\n\nDetails about the work.\n"
    )
    wt = repo / ".cairn" / "worktrees" / "T01"
    (wt / "feature.txt").write_text("new\n")  # uncommitted -> sweep commit happens

    summary = mergeflow.run(repo / ".cairn", "T01")
    assert summary.startswith("OK T01"), summary

    log = _git(["log", "--format=%s", "main"], repo)
    assert "My title" in log
    assert "feat(T01): My title" in log
