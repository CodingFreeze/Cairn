"""End-to-end tests for `cairn merge` — the atomic worktree-merge helper (#16).

Each test builds a real throwaway git repo so the rebase/--no-ff/worktree mechanics
are exercised for real, not mocked.
"""
import json
import subprocess
import sys
from pathlib import Path

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


def _dispatch(tmp_path, tid):
    base_sha = _git(["rev-parse", "main"], tmp_path)
    payload = json.dumps(
        {"id": tid, "goal": f"{tid} work", "status": "dispatched",
         "branch": f"cairn/{tid}", "depends_on": [], "base_sha": base_sha}
    )
    _cli(["board", "add", payload], tmp_path)
    _git(["worktree", "add", "-b", f"cairn/{tid}", f".cairn/worktrees/{tid}", "main"], tmp_path)


def _status(tmp_path, tid):
    r = _cli(["board", "get", tid], tmp_path)
    return json.loads(r.stdout)["status"]


def test_merge_happy_path(tmp_path):
    _repo(tmp_path)
    _dispatch(tmp_path, "T01")
    # uncommitted change in the worktree — the helper must commit it
    (tmp_path / ".cairn" / "worktrees" / "T01" / "greeting.txt").write_text("hi\n")

    r = _cli(["merge", "T01"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("OK T01"), r.stdout

    # change landed on main via a real --no-ff merge commit (2 parents)
    assert (tmp_path / "greeting.txt").exists()
    parents = _git(["rev-list", "--parents", "-n1", "HEAD"], tmp_path).split()
    assert len(parents) == 3, "expected a --no-ff merge commit"
    assert _status(tmp_path, "T01") == "merged"
    assert not (tmp_path / ".cairn" / "worktrees" / "T01").exists()


def test_merge_rebase_conflict_fails_clean(tmp_path):
    _repo(tmp_path)
    _dispatch(tmp_path, "T01")
    wt = tmp_path / ".cairn" / "worktrees" / "T01"
    # ticket edits app.txt one way...
    (wt / "app.txt").write_text("ticket\n")
    _git(["commit", "-am", "ticket edit"], wt)
    # ...main diverges on the same line -> rebase must conflict
    (tmp_path / "app.txt").write_text("main\n")
    _git(["commit", "-am", "main edit"], tmp_path)

    r = _cli(["merge", "T01"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("FAIL T01"), r.stdout
    # nothing half-applied: board untouched, worktree intact, no rebase in progress
    assert _status(tmp_path, "T01") == "dispatched"
    assert wt.exists()
    assert (tmp_path / "app.txt").read_text() == "main\n"
    assert not (wt / ".git" / "rebase-merge").exists()


def test_merge_unknown_ticket_errors(tmp_path):
    _repo(tmp_path)
    r = _cli(["merge", "T99"], tmp_path)
    assert r.returncode != 0
    assert "no such ticket" in r.stderr


def test_merge_refuses_branch_mismatch(tmp_path):
    """[P1] board branch != worktree branch -> refuse before any mutation."""
    _repo(tmp_path)
    _dispatch(tmp_path, "T01")  # worktree is on cairn/T01
    _cli(["board", "set", "T01", "branch=cairn/WRONG"], tmp_path)  # board now lies
    r = _cli(["merge", "T01"], tmp_path)
    assert r.returncode != 0
    assert "mismatch" in r.stderr
    # nothing mutated
    assert _status(tmp_path, "T01") == "dispatched"
    assert (tmp_path / ".cairn" / "worktrees" / "T01").exists()


def test_merge_nonexistent_base_errors(tmp_path):
    """Base must be an existing local branch — reject before any mutation."""
    _repo(tmp_path)
    _dispatch(tmp_path, "T01")
    r = _cli(["merge", "T01", "--base", "nope"], tmp_path)
    assert r.returncode != 0
    assert "not an existing local branch" in r.stderr
    assert _status(tmp_path, "T01") == "dispatched"
