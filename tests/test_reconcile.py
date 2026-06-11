import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import reconcile

import pytest


def _git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True,
    )


def _init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "seed.txt").write_text("seed\n")
    _git(repo, "add", "seed.txt")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def _commit_on_branch(repo, branch, fname, base="main"):
    _git(repo, "checkout", "-q", "-b", branch, base)
    (repo / fname).write_text("x\n")
    _git(repo, "add", fname)
    _git(repo, "commit", "-q", "-m", f"work on {branch}")
    _git(repo, "checkout", "-q", base)


def test_branch_exists_true_and_false(tmp_path):
    repo = _init_repo(tmp_path)
    assert reconcile.branch_exists(repo, "main") is True
    assert reconcile.branch_exists(repo, "cairn/T01") is False


def test_branch_has_commits_ahead(tmp_path):
    repo = _init_repo(tmp_path)
    _commit_on_branch(repo, "cairn/T01", "a.txt")
    assert reconcile.branch_has_commits_ahead(repo, "cairn/T01", "main") is True


def test_branch_no_commits_ahead_when_identical(tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "branch", "cairn/T01", "main")
    assert reconcile.branch_has_commits_ahead(repo, "cairn/T01", "main") is False


def test_is_merged_true_after_merge(tmp_path):
    repo = _init_repo(tmp_path)
    _commit_on_branch(repo, "cairn/T01", "a.txt")
    _git(repo, "merge", "-q", "--no-ff", "cairn/T01", "-m", "merge T01")
    assert reconcile.is_merged(repo, "cairn/T01", "main") is True


def test_is_merged_false_when_unmerged(tmp_path):
    repo = _init_repo(tmp_path)
    _commit_on_branch(repo, "cairn/T01", "a.txt")
    assert reconcile.is_merged(repo, "cairn/T01", "main") is False


def test_is_merged_false_for_missing_branch(tmp_path):
    repo = _init_repo(tmp_path)
    assert reconcile.is_merged(repo, "cairn/T99", "main") is False


def _entry(ticket_id, status, branch=None):
    return {
        "id": ticket_id,
        "status": status,
        "branch": branch or f"cairn/{ticket_id}",
        "depends_on": [],
    }


def test_classify_todo_needs_dispatch(tmp_path):
    repo = _init_repo(tmp_path)
    e = _entry("T01", "todo")
    assert reconcile.classify_ticket_state(repo, "T01", e) == "needs_dispatch"


def test_classify_dispatched_missing_branch_needs_dispatch(tmp_path):
    repo = _init_repo(tmp_path)
    e = _entry("T01", "dispatched")  # branch cairn/T01 never created
    assert reconcile.classify_ticket_state(repo, "T01", e) == "needs_dispatch"


def test_classify_dispatched_empty_branch_resumable(tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "branch", "cairn/T01", "main")  # branch exists, no commits ahead
    e = _entry("T01", "dispatched")
    assert reconcile.classify_ticket_state(repo, "T01", e) == "in_progress_resumable"


def test_classify_dispatched_with_commits_needs_review(tmp_path):
    repo = _init_repo(tmp_path)
    _commit_on_branch(repo, "cairn/T01", "a.txt")
    e = _entry("T01", "dispatched")
    assert reconcile.classify_ticket_state(repo, "T01", e) == "needs_review"


def test_classify_in_progress_with_commits_needs_review(tmp_path):
    repo = _init_repo(tmp_path)
    _commit_on_branch(repo, "cairn/T01", "a.txt")
    e = _entry("T01", "in-progress")
    assert reconcile.classify_ticket_state(repo, "T01", e) == "needs_review"


def test_classify_merged_status(tmp_path):
    repo = _init_repo(tmp_path)
    e = _entry("T01", "merged")
    assert reconcile.classify_ticket_state(repo, "T01", e) == "merged"


def test_classify_merged_by_git_even_if_board_lags(tmp_path):
    repo = _init_repo(tmp_path)
    # Record dispatch-time base tip (the orchestrator always writes base_sha now).
    # Required after the BUG-1 ordering fix: with positive base_sha merge evidence
    # (tip moved past base_sha and is now in base) a no-ff merge is unambiguously
    # 'merged'. An absent-base_sha 0-ahead branch is biased to resumable for safety.
    base_sha = _git(repo, "rev-parse", "main").stdout.strip()
    _commit_on_branch(repo, "cairn/T01", "a.txt")
    _git(repo, "merge", "-q", "--no-ff", "cairn/T01", "-m", "merge T01")
    e = _entry("T01", "dispatched")  # board didn't get updated before crash
    e["base_sha"] = base_sha
    assert reconcile.classify_ticket_state(repo, "T01", e) == "merged"


def test_classify_conflict(tmp_path):
    repo = _init_repo(tmp_path)
    # base changes the same file the branch will change -> rebase conflict
    _git(repo, "checkout", "-q", "-b", "cairn/T01", "main")
    (repo / "clash.txt").write_text("branch version\n")
    _git(repo, "add", "clash.txt")
    _git(repo, "commit", "-q", "-m", "branch clash")
    _git(repo, "checkout", "-q", "main")
    (repo / "clash.txt").write_text("main version\n")
    _git(repo, "add", "clash.txt")
    _git(repo, "commit", "-q", "-m", "main clash")
    e = _entry("T01", "dispatched")
    assert reconcile.classify_ticket_state(repo, "T01", e) == "conflict"


def test_reconcile_board_classifies_each_ticket(tmp_path):
    repo = _init_repo(tmp_path)
    _commit_on_branch(repo, "cairn/T02", "b.txt")  # dispatched + has commits
    board_entries = [
        {"id": "T01", "status": "todo", "branch": "cairn/T01", "depends_on": []},
        {"id": "T02", "status": "dispatched", "branch": "cairn/T02", "depends_on": []},
        {"id": "T03", "status": "merged", "branch": "cairn/T03", "depends_on": []},
    ]
    diff = reconcile.reconcile_board(repo, board_entries)
    by_id = {d["id"]: d["state"] for d in diff}
    assert by_id["T01"] == "needs_dispatch"
    assert by_id["T02"] == "needs_review"
    assert by_id["T03"] == "merged"
    # diff entries carry id, status (board), branch, and computed state
    assert diff[0].keys() >= {"id", "status", "branch", "state"}


# ---------------------------------------------------------------------------
# No-ff merge policy tests — the fix for the merged-detection ambiguity.
# Policy: the orchestrator ALWAYS merges with --no-ff, so after a merge
# base has commits the branch lacks (base_advanced > 0).  A freshly created
# empty branch at base tip does NOT satisfy base_advanced, so the two cases
# are unambiguous.
# ---------------------------------------------------------------------------


def _noff_merge(repo, branch, base="main"):
    """Merge `branch` into `base` with --no-ff (the orchestrator policy)."""
    _git(repo, "checkout", "-q", base)
    _git(repo, "merge", "-q", "--no-ff", branch, "-m", f"merge {branch}")


# NOTE: after the BUG-1 ordering fix these no-ff merged tests record base_sha
# (the dispatch-time base tip the orchestrator always writes). With base_sha the
# branch tip having moved PAST base_sha and now being reachable from base is
# positive merge evidence → 'merged'. Without base_sha a 0-ahead branch is
# ambiguous (untouched vs no-ff merged) and is biased to 'in_progress_resumable'
# for crash-safety; the authoritative status==merged path still covers it.
def test_noff_merged_dispatched_ticket_is_merged(tmp_path):
    """A dispatched ticket whose branch was merged via --no-ff → 'merged'."""
    repo = _init_repo(tmp_path)
    base_sha = _git(repo, "rev-parse", "main").stdout.strip()
    _commit_on_branch(repo, "cairn/T01", "t01.txt")
    _noff_merge(repo, "cairn/T01")
    e = _entry("T01", "dispatched")
    e["base_sha"] = base_sha
    assert reconcile.classify_ticket_state(repo, "T01", e) == "merged"


def test_noff_merged_pr_open_ticket_is_merged(tmp_path):
    """Board shows 'pr-open' but branch was already merged via --no-ff → 'merged'
    (crash-recovery: board wasn't updated after the merge)."""
    repo = _init_repo(tmp_path)
    base_sha = _git(repo, "rev-parse", "main").stdout.strip()
    _commit_on_branch(repo, "cairn/T02", "t02.txt")
    _noff_merge(repo, "cairn/T02")
    e = _entry("T02", "pr-open")
    e["base_sha"] = base_sha
    assert reconcile.classify_ticket_state(repo, "T02", e) == "merged"


def test_noff_merged_blocked_ticket_is_merged(tmp_path):
    """Board shows 'blocked' but branch was already merged via --no-ff → 'merged'
    (crash-recovery: board wasn't updated after the merge)."""
    repo = _init_repo(tmp_path)
    base_sha = _git(repo, "rev-parse", "main").stdout.strip()
    _commit_on_branch(repo, "cairn/T03", "t03.txt")
    _noff_merge(repo, "cairn/T03")
    e = _entry("T03", "blocked")
    e["base_sha"] = base_sha
    assert reconcile.classify_ticket_state(repo, "T03", e) == "merged"


def test_empty_dispatched_branch_is_resumable(tmp_path):
    """A branch created at base tip with 0 commits (just dispatched, no work yet)
    → 'in_progress_resumable', NOT 'merged'.  This is the FF-ambiguity fix:
    an empty branch has tip==base but base has NOT advanced past it."""
    repo = _init_repo(tmp_path)
    _git(repo, "branch", "cairn/T04", "main")  # empty branch at base tip
    e = _entry("T04", "dispatched")
    assert reconcile.classify_ticket_state(repo, "T04", e) == "in_progress_resumable"


def test_dispatched_branch_with_commits_ahead_is_needs_review(tmp_path):
    """A dispatched branch with commits that merge cleanly → 'needs_review'."""
    repo = _init_repo(tmp_path)
    _commit_on_branch(repo, "cairn/T05", "t05.txt")
    e = _entry("T05", "dispatched")
    assert reconcile.classify_ticket_state(repo, "T05", e) == "needs_review"


def test_dispatched_branch_with_conflict_is_conflict(tmp_path):
    """A dispatched branch whose commits would conflict with base → 'conflict'."""
    repo = _init_repo(tmp_path)
    # Create conflicting edits on branch and base for the same file.
    _git(repo, "checkout", "-q", "-b", "cairn/T06", "main")
    (repo / "conflict.txt").write_text("branch version\n")
    _git(repo, "add", "conflict.txt")
    _git(repo, "commit", "-q", "-m", "branch adds conflict.txt")
    _git(repo, "checkout", "-q", "main")
    (repo / "conflict.txt").write_text("main version\n")
    _git(repo, "add", "conflict.txt")
    _git(repo, "commit", "-q", "-m", "main adds conflict.txt")
    e = _entry("T06", "dispatched")
    assert reconcile.classify_ticket_state(repo, "T06", e) == "conflict"


def test_missing_branch_is_needs_dispatch(tmp_path):
    """A ticket whose branch does not exist at all → 'needs_dispatch'."""
    repo = _init_repo(tmp_path)
    e = _entry("T99", "dispatched")  # branch cairn/T99 never created
    assert reconcile.classify_ticket_state(repo, "T99", e) == "needs_dispatch"

