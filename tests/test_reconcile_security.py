"""Reconcile hardening: base_sha fast-forward detection + git arg-injection guards."""
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


def _entry(ticket_id, status, branch=None):
    return {
        "id": ticket_id,
        "status": status,
        "branch": branch or f"cairn/{ticket_id}",
        "depends_on": [],
    }


def _rev_parse(repo, ref):
    return _git(repo, "rev-parse", ref).stdout.strip()


# --- base_sha fast-forward merge robustness ---

def test_base_sha_ff_merge_is_merged(tmp_path):
    """A ticket dispatched with base_sha recorded, then fast-forward merged into
    base, classifies as 'merged' even though there is no --no-ff merge commit."""
    repo = _init_repo(tmp_path)
    base_sha = _rev_parse(repo, "main")  # base tip at dispatch time
    _commit_on_branch(repo, "cairn/T01", "ff.txt")
    # Fast-forward merge: main moves to the branch tip, no merge commit.
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "cairn/T01")
    e = _entry("T01", "dispatched")
    e["base_sha"] = base_sha
    assert reconcile.classify_ticket_state(repo, "T01", e) == "merged"


def test_base_sha_empty_branch_is_resumable(tmp_path):
    """An empty dispatched branch whose tip == base_sha → 'in_progress_resumable'
    (no work yet, not a fast-forward merge)."""
    repo = _init_repo(tmp_path)
    base_sha = _rev_parse(repo, "main")
    _git(repo, "branch", "cairn/T02", "main")  # empty branch at base tip
    e = _entry("T02", "dispatched")
    e["base_sha"] = base_sha
    assert reconcile.classify_ticket_state(repo, "T02", e) == "in_progress_resumable"


def test_base_sha_empty_branch_after_base_advanced_is_resumable(tmp_path):
    """REGRESSION (BUG 1): an EMPTY dispatched branch (tip == recorded base_sha)
    must stay 'in_progress_resumable' even after base advances (other tickets
    merged). Before the ordering fix the empty branch tip is an ancestor of the
    advanced base (tip_in_base) AND base moved past it (base_advanced), so the
    no-ff merged check wrongly classified genuinely-unfinished work as 'merged'
    and cairn-resume would SKIP it."""
    repo = _init_repo(tmp_path)
    base_sha = _rev_parse(repo, "main")  # base tip at dispatch
    _git(repo, "branch", "cairn/T01", "main")  # empty branch at base tip
    # Base advances after dispatch (another ticket merged onto main).
    _git(repo, "checkout", "-q", "main")
    (repo / "other.txt").write_text("other ticket\n")
    _git(repo, "add", "other.txt")
    _git(repo, "commit", "-q", "-m", "other ticket merged")
    e = _entry("T01", "dispatched")
    e["base_sha"] = base_sha
    assert reconcile.classify_ticket_state(repo, "T01", e) == "in_progress_resumable"


def test_no_base_sha_empty_branch_after_base_advanced_is_resumable(tmp_path):
    """SAFETY (BUG 1 edge): a legacy entry with NO base_sha whose branch has zero
    commits ahead and base advanced is ambiguous (empty-untouched vs no-ff merged).
    Bias to safety → 'in_progress_resumable' (re-dispatch is safe; skipping
    unfinished work is not). The authoritative status==merged path covers truly
    merged tickets."""
    repo = _init_repo(tmp_path)
    _git(repo, "branch", "cairn/T07", "main")  # empty branch at base tip
    _git(repo, "checkout", "-q", "main")
    (repo / "other2.txt").write_text("other\n")
    _git(repo, "add", "other2.txt")
    _git(repo, "commit", "-q", "-m", "base advances")
    e = _entry("T07", "dispatched")  # no base_sha (legacy)
    assert reconcile.classify_ticket_state(repo, "T07", e) == "in_progress_resumable"


# --- git arg-injection guards on base/branch ---

def test_classify_rejects_dashed_base(tmp_path):
    """A base value starting with '-' could be parsed as a git option → reject."""
    repo = _init_repo(tmp_path)
    e = _entry("T01", "dispatched")
    with pytest.raises(ValueError):
        reconcile.classify_ticket_state(repo, "T01", e, base="-x")


def test_classify_rejects_upload_pack_base(tmp_path):
    repo = _init_repo(tmp_path)
    e = _entry("T01", "dispatched")
    with pytest.raises(ValueError):
        reconcile.classify_ticket_state(repo, "T01", e, base="--upload-pack=evil")


def test_reconcile_board_rejects_dashed_base(tmp_path):
    repo = _init_repo(tmp_path)
    entries = [{"id": "T01", "status": "todo", "branch": "cairn/T01", "depends_on": []}]
    with pytest.raises(ValueError):
        reconcile.reconcile_board(repo, entries, base="-x")


def test_classify_rejects_dashed_branch(tmp_path):
    repo = _init_repo(tmp_path)
    e = _entry("T01", "dispatched", branch="--upload-pack=evil")
    with pytest.raises(ValueError):
        reconcile.classify_ticket_state(repo, "T01", e)
