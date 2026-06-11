import json
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parent.parent / "bin" / "cairn"


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, str(CLI), *args], cwd=cwd, capture_output=True, text=True,
    )


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)


def _setup(tmp_path):
    repo = tmp_path
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "seed.txt").write_text("seed\n")
    _git(repo, "add", "seed.txt")
    _git(repo, "commit", "-q", "-m", "seed")
    assert _run(["init", "--existing"], repo).returncode == 0
    return repo


def test_classify_single_ticket_todo(tmp_path):
    repo = _setup(tmp_path)
    _run(["board", "add", '{"id": "T01"}'], repo)
    r = _run(["classify", "T01"], repo)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "needs_dispatch"


def test_classify_dispatched_with_commits_needs_review(tmp_path):
    repo = _setup(tmp_path)
    _run(["board", "add", '{"id": "T01"}'], repo)
    _run(["board", "set", "T01", "status=dispatched", "branch=cairn/T01"], repo)
    _git(repo, "checkout", "-q", "-b", "cairn/T01", "main")
    (repo / "a.txt").write_text("x\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "work")
    _git(repo, "checkout", "-q", "main")
    r = _run(["classify", "T01"], repo)
    assert r.stdout.strip() == "needs_review"


def test_reconcile_emits_json(tmp_path):
    repo = _setup(tmp_path)
    _run(["board", "add", '{"id": "T01"}'], repo)
    _run(["board", "add", '{"id": "T02", "depends_on": ["T01"]}'], repo)
    r = _run(["reconcile"], repo)
    assert r.returncode == 0, r.stderr
    diff = json.loads(r.stdout)
    by_id = {d["id"]: d["state"] for d in diff}
    assert by_id == {"T01": "needs_dispatch", "T02": "needs_dispatch"}


def test_reconcile_respects_base_flag(tmp_path):
    repo = _setup(tmp_path)
    _run(["board", "add", '{"id": "T01"}'], repo)
    r = _run(["reconcile", "--base", "main"], repo)
    assert r.returncode == 0, r.stderr


def test_reconcile_rejects_dashed_base(tmp_path):
    repo = _setup(tmp_path)
    _run(["board", "add", '{"id": "T01"}'], repo)
    r = _run(["reconcile", "--base", "-x"], repo)
    assert r.returncode != 0
    assert "error" in (r.stderr + r.stdout).lower()
    assert "Traceback" not in r.stderr


def test_classify_rejects_dashed_base(tmp_path):
    repo = _setup(tmp_path)
    _run(["board", "add", '{"id": "T01"}'], repo)
    r = _run(["classify", "T01", "--base", "--upload-pack=evil"], repo)
    assert r.returncode != 0
    assert "error" in (r.stderr + r.stdout).lower()
    assert "Traceback" not in r.stderr


# --- Fix 3: CLI --base must be a real existing ref (not just non-dashed) ---

def test_classify_rejects_nonexistent_base(tmp_path):
    """cairn classify with a typo'd --base that doesn't exist → rc!=0, error in output."""
    repo = _setup(tmp_path)
    _run(["board", "add", '{"id": "T01"}'], repo)
    r = _run(["classify", "T01", "--base", "nonexistent-branch"], repo)
    assert r.returncode != 0
    assert "error" in (r.stderr + r.stdout).lower()
    assert "Traceback" not in r.stderr


def test_reconcile_rejects_nonexistent_base(tmp_path):
    """cairn reconcile with a nonexistent --base → rc!=0, error in output, no Traceback."""
    repo = _setup(tmp_path)
    _run(["board", "add", '{"id": "T01"}'], repo)
    r = _run(["reconcile", "--base", "nope"], repo)
    assert r.returncode != 0
    assert "error" in (r.stderr + r.stdout).lower()
    assert "Traceback" not in r.stderr


def test_classify_valid_existing_branch(tmp_path):
    """cairn classify still works with a valid existing branch."""
    repo = _setup(tmp_path)
    _run(["board", "add", '{"id": "T01"}'], repo)
    r = _run(["classify", "T01", "--base", "main"], repo)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "needs_dispatch"


def test_reconcile_valid_existing_branch(tmp_path):
    """cairn reconcile still works with a valid existing branch."""
    repo = _setup(tmp_path)
    _run(["board", "add", '{"id": "T01"}'], repo)
    r = _run(["reconcile", "--base", "main"], repo)
    assert r.returncode == 0, r.stderr
