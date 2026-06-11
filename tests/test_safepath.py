import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import safepath

import pytest


def test_ensure_within_allows_normal_path(tmp_path):
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    target = cairn / "vault" / "decisions.md"
    # Should not raise; returns a realpath string.
    out = safepath.ensure_within(cairn, target)
    assert str(out).endswith("decisions.md")


def test_ensure_within_allows_nonexistent_leaf(tmp_path):
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    target = cairn / "vault" / "newfile.md"  # does not exist yet
    safepath.ensure_within(cairn, target)  # must not raise


def test_ensure_within_rejects_symlinked_leaf(tmp_path):
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    link = cairn / "vault" / "decisions.md"
    link.symlink_to(outside)
    with pytest.raises(ValueError):
        safepath.ensure_within(cairn, link)


def test_ensure_within_rejects_symlinked_parent(tmp_path):
    cairn = tmp_path / ".cairn"
    cairn.mkdir(parents=True)
    outside_dir = tmp_path / "elsewhere"
    outside_dir.mkdir()
    (cairn / "vault").symlink_to(outside_dir)
    target = cairn / "vault" / "decisions.md"
    with pytest.raises(ValueError):
        safepath.ensure_within(cairn, target)


def test_ensure_within_rejects_escape_via_dotdot(tmp_path):
    cairn = tmp_path / ".cairn"
    cairn.mkdir(parents=True)
    target = cairn / ".." / "outside.md"
    with pytest.raises(ValueError):
        safepath.ensure_within(cairn, target)


# --- assert_safe_root ---

def test_assert_safe_root_allows_real_dir(tmp_path):
    cairn = tmp_path / ".cairn"
    cairn.mkdir(parents=True)
    out = safepath.assert_safe_root(cairn)
    assert out == os.path.realpath(str(cairn))


def test_assert_safe_root_rejects_symlinked_root(tmp_path):
    real = tmp_path / "real_cairn"
    real.mkdir()
    link = tmp_path / ".cairn"
    link.symlink_to(real)
    with pytest.raises(ValueError):
        safepath.assert_safe_root(link)


# --- safe_open_read ---

def test_safe_open_read_reads_normal_file(tmp_path):
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    p = cairn / "vault" / "decisions.md"
    p.write_text("hello world\n")
    with safepath.safe_open_read(cairn, p) as fh:
        assert fh.read() == "hello world\n"


def test_safe_open_read_rejects_symlinked_leaf(tmp_path):
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    outside = tmp_path / "secret.txt"
    outside.write_text("SECRET\n")
    link = cairn / "vault" / "decisions.md"
    link.symlink_to(outside)
    with pytest.raises((ValueError, OSError)):
        with safepath.safe_open_read(cairn, link) as fh:
            fh.read()


# --- safe_open_write_create ---

def test_safe_open_write_create_writes_normal_file(tmp_path):
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    p = cairn / "vault" / "decisions.md"
    with safepath.safe_open_write_create(cairn, p) as fh:
        fh.write("written\n")
    assert p.read_text() == "written\n"


def test_safe_open_write_create_rejects_symlinked_leaf(tmp_path):
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("ORIGINAL\n")
    link = cairn / "vault" / "decisions.md"
    link.symlink_to(outside)
    with pytest.raises((ValueError, OSError)):
        with safepath.safe_open_write_create(cairn, link) as fh:
            fh.write("clobber\n")
    # The outside file must be untouched.
    assert outside.read_text() == "ORIGINAL\n"


# --- safe_mkdir ---

def test_safe_mkdir_creates_nested(tmp_path):
    cairn = tmp_path / ".cairn"
    cairn.mkdir(parents=True)
    target = cairn / "handoff"
    safepath.safe_mkdir(cairn, target)
    assert target.is_dir()


def test_safe_mkdir_rejects_symlinked_component(tmp_path):
    cairn = tmp_path / ".cairn"
    cairn.mkdir(parents=True)
    outside_dir = tmp_path / "elsewhere"
    outside_dir.mkdir()
    (cairn / "vault").symlink_to(outside_dir)
    target = cairn / "vault" / "sub"
    with pytest.raises(ValueError):
        safepath.safe_mkdir(cairn, target)
    # No directory created through the symlink.
    assert not (outside_dir / "sub").exists()


def test_safe_mkdir_rejects_under_symlinked_root(tmp_path):
    real = tmp_path / "real_cairn"
    real.mkdir()
    link = tmp_path / ".cairn"
    link.symlink_to(real)
    with pytest.raises(ValueError):
        safepath.safe_mkdir(link, link / "handoff")


# ---------------------------------------------------------------------------
# Phase 10: dir-fd-anchored traversal — refuse a SYMLINKED INTERMEDIATE
# directory component (the TOCTOU-racy case the old by-name open could escape).
# ---------------------------------------------------------------------------

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


def test_walk_to_parent_rejects_symlinked_intermediate(tmp_path):
    cairn, target, _outside_dir, _outside_file = _plant_symlinked_intermediate(tmp_path)
    with pytest.raises(ValueError):
        fd, _name = safepath._walk_to_parent(cairn, target)
        os.close(fd)


def test_safe_open_read_rejects_symlinked_intermediate(tmp_path):
    cairn, target, _outside_dir, _outside_file = _plant_symlinked_intermediate(tmp_path)
    with pytest.raises((ValueError, OSError)):
        with safepath.safe_open_read(cairn, target) as fh:
            # If this ever returned, the outside SECRET must NOT be leaked.
            assert "SECRET" not in fh.read()


def test_safe_open_append_rejects_symlinked_intermediate(tmp_path):
    cairn, target, _outside_dir, outside_file = _plant_symlinked_intermediate(tmp_path)
    with pytest.raises((ValueError, OSError)):
        with safepath.safe_open_append(cairn, target) as fh:
            fh.write("appended\n")
    assert outside_file.read_text() == "SECRET\n"  # untouched


def test_safe_open_write_create_rejects_symlinked_intermediate(tmp_path):
    cairn, target, _outside_dir, outside_file = _plant_symlinked_intermediate(tmp_path)
    with pytest.raises((ValueError, OSError)):
        with safepath.safe_open_write_create(cairn, target) as fh:
            fh.write("clobber\n")
    assert outside_file.read_text() == "SECRET\n"  # not clobbered


def test_safe_unlink_rejects_symlinked_intermediate(tmp_path):
    cairn, target, _outside_dir, outside_file = _plant_symlinked_intermediate(tmp_path)
    with pytest.raises((ValueError, OSError)):
        safepath.safe_unlink(cairn, target)
    assert outside_file.exists()  # outside file NOT removed


def test_safe_mkdir_rejects_symlinked_intermediate(tmp_path):
    cairn = tmp_path / ".cairn"
    cairn.mkdir(parents=True)
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    (cairn / "handoff").symlink_to(outside_dir)
    target = cairn / "handoff" / "sub"
    with pytest.raises((ValueError, OSError)):
        safepath.safe_mkdir(cairn, target)
    assert not (outside_dir / "sub").exists()  # nothing created through the symlink


# --- happy paths for the new anchored helpers ------------------------------

def test_safe_open_append_creates_and_appends(tmp_path):
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    p = cairn / "vault" / "decisions.md"
    with safepath.safe_open_append(cairn, p) as fh:
        fh.write("one\n")
    with safepath.safe_open_append(cairn, p) as fh:
        fh.write("two\n")
    assert p.read_text() == "one\ntwo\n"


def test_safe_unlink_removes_normal_file(tmp_path):
    cairn = tmp_path / ".cairn"
    (cairn / "handoff").mkdir(parents=True)
    p = cairn / "handoff" / "dismiss-candidates.json"
    p.write_text("[]")
    safepath.safe_unlink(cairn, p)
    assert not p.exists()


def test_safe_mkdir_creates_deeply_nested(tmp_path):
    cairn = tmp_path / ".cairn"
    cairn.mkdir(parents=True)
    target = cairn / "a" / "b" / "c"
    safepath.safe_mkdir(cairn, target)
    assert target.is_dir()


def test_walk_to_parent_refuses_root_as_leaf(tmp_path):
    cairn = tmp_path / ".cairn"
    cairn.mkdir(parents=True)
    with pytest.raises(ValueError):
        safepath._walk_to_parent(cairn, cairn)


def test_safe_unlink_refuses_escape_via_dotdot(tmp_path):
    cairn = tmp_path / ".cairn"
    cairn.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("keep\n")
    with pytest.raises(ValueError):
        safepath.safe_unlink(cairn, cairn / ".." / "outside.txt")
    assert outside.exists()
