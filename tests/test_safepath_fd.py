"""Phase 11: renameat-anchored atomic_write + dir-fd lock open.

Final-commit (rename) and lock-open steps anchored to validated dir fds so there
is no pathname re-resolution left to race. Split out of test_safepath.py to keep
both test files under the 300-line cap.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import safepath

import pytest


def _plant_symlinked_intermediate(tmp_path, leaf_name="latest.md", payload="SECRET\n"):
    """Build .cairn/handoff -> outside_dir, where outside_dir holds a file.

    Returns (cairn, target, outside_dir, outside_file). The intermediate
    component `handoff` is a symlink to an outside directory, so opening
    .cairn/handoff/<leaf> by name would escape the root.
    """
    cairn = tmp_path / ".cairn"
    cairn.mkdir(parents=True)
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    outside_file = outside_dir / leaf_name
    outside_file.write_text(payload)
    (cairn / "handoff").symlink_to(outside_dir)
    target = cairn / "handoff" / leaf_name
    return cairn, target, outside_dir, outside_file


# --- atomic_write ---

def test_atomic_write_writes_and_leaves_no_tmp(tmp_path):
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    p = cairn / "vault" / "decisions.md"
    safepath.atomic_write(cairn, p, "hello atomic\n")
    assert p.read_text() == "hello atomic\n"
    # No .tmp residue in the target directory.
    assert list((cairn / "vault").glob("*.tmp")) == []
    assert list((cairn / "vault").glob(".*.tmp")) == []


def test_atomic_write_overwrites_existing(tmp_path):
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    p = cairn / "vault" / "decisions.md"
    p.write_text("OLD\n")
    safepath.atomic_write(cairn, p, "NEW\n")
    assert p.read_text() == "NEW\n"
    assert list((cairn / "vault").glob("*.tmp")) == []
    assert list((cairn / "vault").glob(".*.tmp")) == []


def test_atomic_write_rejects_symlinked_intermediate(tmp_path):
    cairn, target, _outside_dir, outside_file = _plant_symlinked_intermediate(tmp_path)
    with pytest.raises((ValueError, OSError)):
        safepath.atomic_write(cairn, target, "clobber\n")
    # The outside file behind the symlinked parent must be untouched.
    assert outside_file.read_text() == "SECRET\n"
    # And no tmp left behind anywhere relevant.
    assert list(_outside_dir.glob("*.tmp")) == []
    assert list(_outside_dir.glob(".*.tmp")) == []


def test_atomic_write_refuses_symlinked_leaf(tmp_path):
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("ORIGINAL\n")
    link = cairn / "vault" / "decisions.md"
    link.symlink_to(outside)
    with pytest.raises(ValueError):
        safepath.atomic_write(cairn, link, "clobber\n")
    # The outside file behind the symlinked leaf must be untouched.
    assert outside.read_text() == "ORIGINAL\n"


def test_atomic_write_refuses_escape_via_dotdot(tmp_path):
    cairn = tmp_path / ".cairn"
    cairn.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("keep\n")
    with pytest.raises(ValueError):
        safepath.atomic_write(cairn, cairn / ".." / "outside.txt", "clobber\n")
    assert outside.read_text() == "keep\n"


# --- open_dir_fd ---

def test_open_dir_fd_opens_root_and_subparts(tmp_path):
    cairn = tmp_path / ".cairn"
    (cairn / "handoff").mkdir(parents=True)
    dfd = safepath.open_dir_fd(cairn)
    try:
        assert os.path.samestat(os.fstat(dfd), os.stat(str(cairn)))
    finally:
        os.close(dfd)
    sub = safepath.open_dir_fd(cairn, "handoff")
    try:
        assert os.path.samestat(os.fstat(sub), os.stat(str(cairn / "handoff")))
    finally:
        os.close(sub)


def test_open_dir_fd_rejects_symlinked_root(tmp_path):
    real = tmp_path / "real_cairn"
    real.mkdir()
    link = tmp_path / ".cairn"
    link.symlink_to(real)
    with pytest.raises(ValueError):
        safepath.open_dir_fd(link)


def test_open_dir_fd_rejects_symlinked_subpart(tmp_path):
    cairn = tmp_path / ".cairn"
    cairn.mkdir(parents=True)
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    (cairn / "handoff").symlink_to(outside_dir)
    with pytest.raises(ValueError):
        safepath.open_dir_fd(cairn, "handoff")


# --- open_lock_fd ---

def test_open_lock_fd_returns_usable_fd(tmp_path):
    cairn = tmp_path / ".cairn"
    cairn.mkdir(parents=True)
    lfd = safepath.open_lock_fd(cairn, "board.lock")
    try:
        assert isinstance(lfd, int) and lfd >= 0
        os.write(lfd, b"")  # fd is writable (O_RDWR)
        assert (cairn / "board.lock").exists()
    finally:
        os.close(lfd)


def test_open_lock_fd_rejects_symlinked_root(tmp_path):
    real = tmp_path / "real_cairn"
    real.mkdir()
    link = tmp_path / ".cairn"
    link.symlink_to(real)
    with pytest.raises(ValueError):
        safepath.open_lock_fd(link, "board.lock")
