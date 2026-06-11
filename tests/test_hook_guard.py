"""Guard the SessionEnd dismiss hook against a planted symlinked candidates file.

The hook reads .cairn/handoff/dismiss-candidates.json and passes its contents as
argv to `cairn dismiss`. A malicious repo could plant that file as a symlink to
an outside secret so the auto-running hook leaks it. The hook must SKIP a
non-regular / symlinked candidates file (never `cat` it) and always exit 0.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "cairn-dismiss-hook.sh"
CLI = Path(__file__).resolve().parent.parent / "bin" / "cairn"


def _init(repo):
    subprocess.run(
        [sys.executable, str(CLI), "init", "--greenfield"],
        cwd=repo, capture_output=True, text=True, check=True,
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_hook_skips_symlinked_candidates_and_exits_zero(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init(repo)

    # Plant the candidates file as a symlink to an outside secret.
    outside = tmp_path / "secret.txt"
    outside.write_text("SECRET-CONTENTS\n")
    cand = repo / ".cairn" / "handoff" / "dismiss-candidates.json"
    cand.symlink_to(outside)

    payload = '{"cwd": "%s"}' % str(repo)
    r = subprocess.run(
        ["bash", str(HOOK)],
        input=payload, cwd=repo, capture_output=True, text=True,
    )

    # Hook is non-blocking: always exit 0.
    assert r.returncode == 0, (r.stdout, r.stderr)
    # The secret must NOT be leaked into the hook's output.
    assert "SECRET-CONTENTS" not in (r.stdout + r.stderr)
    # The outside secret must be untouched (hook must not rm through the symlink).
    assert outside.exists() and outside.read_text() == "SECRET-CONTENTS\n"
    # The guard must SKIP the symlink entirely — it must NOT cat+rm it. Proof:
    # the planted symlink is left in place (the read/rm branch was skipped).
    assert os.path.islink(str(cand)), "hook must skip (not consume) a symlinked candidates file"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_hook_handles_regular_candidates_file(tmp_path):
    """Sanity: a real (non-symlink) candidates file is still processed and removed."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init(repo)

    cand = repo / ".cairn" / "handoff" / "dismiss-candidates.json"
    cand.write_text('[{"kind": "decisions", "text": "chose flat-file vault"}]')

    payload = '{"cwd": "%s"}' % str(repo)
    r = subprocess.run(
        ["bash", str(HOOK)],
        input=payload, cwd=repo, capture_output=True, text=True,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    # A regular candidates file is consumed (removed) by the hook.
    assert not cand.exists()


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_hook_symlinked_handoff_parent_exits_zero_and_does_not_delete(tmp_path):
    """Hook-level: .cairn/handoff is a symlink to an outside dir containing the
    candidates file. The hook must exit 0 (never block teardown), the outside file
    must NOT be read into the vault, and must NOT be deleted."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init(repo)

    outside_dir = tmp_path / "outside_handoff"
    outside_dir.mkdir()
    outside_cand = outside_dir / "dismiss-candidates.json"
    outside_cand.write_text('[{"kind": "decisions", "text": "We decided to use Postgres for storage"}]')

    # Replace .cairn/handoff with a symlink to outside dir.
    handoff_dir = repo / ".cairn" / "handoff"
    shutil.rmtree(str(handoff_dir), ignore_errors=True)
    handoff_dir.symlink_to(outside_dir)

    payload = '{"cwd": "%s"}' % str(repo)
    r = subprocess.run(
        ["bash", str(HOOK)],
        input=payload, cwd=repo, capture_output=True, text=True,
    )

    # Hook must never block session teardown — always exit 0.
    assert r.returncode == 0, (r.stdout, r.stderr)
    # Outside file must NOT be deleted.
    assert outside_cand.exists(), "hook must not delete outside file through symlinked parent"
    # Outside content must NOT appear in the vault.
    decisions_file = repo / ".cairn" / "vault" / "decisions.md"
    if decisions_file.exists():
        assert "Postgres for storage" not in decisions_file.read_text(), \
            "hook must not harvest from outside file through symlinked handoff parent"
