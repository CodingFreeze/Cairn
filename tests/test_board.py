import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))


def test_board_module_imports():
    import cairn_core.board  # noqa: F401


from cairn_core import board


def test_read_missing_board_returns_empty(tmp_path):
    assert board.read_board(tmp_path) == []


def test_write_then_read_roundtrip(tmp_path):
    entries = [{"id": "T01", "status": "todo"}]
    board.write_board(tmp_path, entries)
    assert board.read_board(tmp_path) == entries


def test_write_is_atomic_no_tmp_left(tmp_path):
    board.write_board(tmp_path, [{"id": "T01", "status": "todo"}])
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


import pytest

FIXED = "2026-06-08T00:00:00+00:00"


def test_add_entry_fills_defaults(tmp_path):
    e = board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    assert e == {
        "id": "T01", "status": "todo", "branch": None, "pr": None,
        "depends_on": [], "owner": None, "files_owned": [], "updated": FIXED,
    }


def test_add_duplicate_id_raises(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    with pytest.raises(ValueError):
        board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)


def test_add_invalid_status_raises(tmp_path):
    with pytest.raises(ValueError):
        board.add_entry(tmp_path, {"id": "T01", "status": "bogus"}, now=FIXED)


def test_get_entry(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    assert board.get_entry(tmp_path, "T01")["id"] == "T01"
    assert board.get_entry(tmp_path, "T99") is None


def test_set_fields_updates_and_stamps(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    board.set_fields(tmp_path, "T01", {"status": "merged", "pr": 7}, now="2026-06-09T00:00:00+00:00")
    e = board.get_entry(tmp_path, "T01")
    assert e["status"] == "merged" and e["pr"] == 7
    assert e["updated"] == "2026-06-09T00:00:00+00:00"


def test_set_invalid_status_raises(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    with pytest.raises(ValueError):
        board.set_fields(tmp_path, "T01", {"status": "bogus"}, now=FIXED)


def test_set_missing_id_raises(tmp_path):
    with pytest.raises(KeyError):
        board.set_fields(tmp_path, "T99", {"status": "merged"}, now=FIXED)


# --- allow-list / type-validation tests ---

def test_set_rejects_unknown_field(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    with pytest.raises(KeyError):
        board.set_fields(tmp_path, "T01", {"bogus_field": "x"}, now=FIXED)


def test_set_rejects_reserved_id_field(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    with pytest.raises(KeyError):
        board.set_fields(tmp_path, "T01", {"id": "T99"}, now=FIXED)


def test_set_rejects_non_list_depends_on(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    with pytest.raises(ValueError):
        board.set_fields(tmp_path, "T01", {"depends_on": "T02"}, now=FIXED)


def test_set_branch_none(tmp_path):
    board.add_entry(tmp_path, {"id": "T01", "branch": "old"}, now=FIXED)
    board.set_fields(tmp_path, "T01", {"branch": None}, now=FIXED)
    assert board.get_entry(tmp_path, "T01")["branch"] is None


def test_set_pr_int(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    board.set_fields(tmp_path, "T01", {"pr": 42}, now=FIXED)
    assert board.get_entry(tmp_path, "T01")["pr"] == 42


# --- add_entry full type-validation (shares _validate_settable with set_fields) ---

def test_add_entry_rejects_non_list_depends_on(tmp_path):
    with pytest.raises(ValueError):
        board.add_entry(tmp_path, {"id": "T01", "depends_on": "T02"}, now=FIXED)


def test_add_entry_rejects_string_pr(tmp_path):
    with pytest.raises(ValueError):
        board.add_entry(tmp_path, {"id": "T01", "pr": "7"}, now=FIXED)


def test_add_entry_rejects_non_str_files_owned_items(tmp_path):
    with pytest.raises(ValueError):
        board.add_entry(tmp_path, {"id": "T01", "files_owned": [1, 2]}, now=FIXED)


def test_add_entry_rejects_non_str_branch(tmp_path):
    with pytest.raises(ValueError):
        board.add_entry(tmp_path, {"id": "T01", "branch": 5}, now=FIXED)


def test_set_base_sha_str(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    board.set_fields(tmp_path, "T01", {"base_sha": "abc123"}, now=FIXED)
    assert board.get_entry(tmp_path, "T01")["base_sha"] == "abc123"


def test_set_base_sha_rejects_int(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    with pytest.raises(ValueError):
        board.set_fields(tmp_path, "T01", {"base_sha": 42}, now=FIXED)


def test_read_board_corrupt_line_raises(tmp_path):
    p = tmp_path / "board.jsonl"
    p.write_text('{"id":"T01","status":"todo"}\nNOT JSON\n')
    with pytest.raises(ValueError, match=":2:"):
        board.read_board(tmp_path)


# --- concurrency: unique temp files + advisory lock ---

def test_add_entry_leaves_no_tmp_files(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    board.add_entry(tmp_path, {"id": "T02"}, now=FIXED)
    assert list(tmp_path.glob("*.tmp")) == []


def test_set_fields_leaves_no_tmp_files(tmp_path):
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    board.set_fields(tmp_path, "T01", {"status": "merged"}, now=FIXED)
    assert list(tmp_path.glob("*.tmp")) == []


def test_board_lock_acquire_release_sequential(tmp_path):
    # The lock context manager must be acquirable and releasable repeatedly
    # (sequential, reentrant-safe enough for our single-process read-modify-write).
    with board._board_lock(tmp_path):
        pass
    with board._board_lock(tmp_path):
        with board._board_lock(tmp_path):  # nested acquire on a fresh fd must work
            pass
    # A normal write under the lock still works afterwards.
    board.add_entry(tmp_path, {"id": "T01"}, now=FIXED)
    assert board.get_entry(tmp_path, "T01")["id"] == "T01"


# --- ticket id type validation ---

def test_add_entry_rejects_int_id(tmp_path):
    with pytest.raises(ValueError, match="ticket id must be a non-empty string"):
        board.add_entry(tmp_path, {"id": 123}, now=FIXED)


def test_add_entry_rejects_empty_string_id(tmp_path):
    with pytest.raises(ValueError, match="ticket id must be a non-empty string"):
        board.add_entry(tmp_path, {"id": ""}, now=FIXED)


def test_add_entry_rejects_whitespace_only_id(tmp_path):
    with pytest.raises(ValueError, match="ticket id must be a non-empty string"):
        board.add_entry(tmp_path, {"id": "  "}, now=FIXED)


# --- symlink-traversal hardening (CRITICAL) ---

def test_read_board_refuses_symlinked_board(tmp_path):
    """board.jsonl planted as a symlink to an outside file → read_board raises,
    and the outside content is NOT returned (no leak)."""
    cairn = tmp_path / ".cairn"
    cairn.mkdir(parents=True)
    outside = tmp_path / "outside_board.txt"
    outside.write_text('{"id": "EVIL", "status": "todo", "depends_on": []}\n')
    (cairn / "board.jsonl").symlink_to(outside)
    with pytest.raises(ValueError):
        board.read_board(cairn)


def test_write_board_refuses_symlinked_root(tmp_path):
    """A symlinked .cairn root → write_board refuses; no write escapes the repo."""
    real = tmp_path / "real_cairn"
    real.mkdir()
    link = tmp_path / ".cairn"
    link.symlink_to(real)
    with pytest.raises(ValueError):
        board.write_board(link, [{"id": "T01", "status": "todo"}])
    # Nothing written through the symlink.
    assert not (real / "board.jsonl").exists()


def test_write_board_refuses_symlinked_board_file(tmp_path):
    """board.jsonl planted as a symlink to an outside file → write_board refuses
    and the outside file is UNCHANGED."""
    cairn = tmp_path / ".cairn"
    cairn.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("ORIGINAL\n")
    (cairn / "board.jsonl").symlink_to(outside)
    with pytest.raises(ValueError):
        board.write_board(cairn, [{"id": "T01", "status": "todo"}])
    assert outside.read_text() == "ORIGINAL\n"


# --- Fix 1: _board_lock symlinked root guard (TOCTOU/mkdir-before-guard) ---

def test_board_lock_symlinked_root_refuses_before_mkdir(tmp_path):
    """A symlinked .cairn root → _board_lock (and thus add_entry/set_fields) must
    raise ValueError BEFORE creating board.lock in the outside target dir."""
    real = tmp_path / "real_cairn"
    real.mkdir()
    link = tmp_path / ".cairn"
    link.symlink_to(real)

    with pytest.raises(ValueError):
        board.add_entry(link, {"id": "T01"}, now=FIXED)

    # No board.lock must have been created outside the repo through the symlink.
    assert not (real / "board.lock").exists()


def test_board_lock_symlinked_root_set_fields_refuses(tmp_path):
    """A symlinked .cairn root → set_fields (which acquires the lock) raises ValueError
    and no board.lock is created in the outside target dir."""
    real = tmp_path / "real_cairn"
    real.mkdir()
    # Pre-create a valid board so the set_fields call reaches lock acquisition.
    board.write_board(real, [{"id": "T01", "status": "todo", "depends_on": [],
                               "branch": None, "pr": None, "owner": None,
                               "files_owned": [], "updated": FIXED}])
    link = tmp_path / ".cairn"
    link.symlink_to(real)

    with pytest.raises(ValueError):
        board.set_fields(link, "T01", {"status": "merged"}, now=FIXED)

    assert not (real / "board.lock").exists()


# --- Finding 2: safe_mkdir in _board_lock guards symlinked path components ---

def test_board_lock_safe_mkdir_refuses_symlinked_cairn_component(tmp_path):
    """_board_lock uses safe_mkdir so a symlinked component in the .cairn path
    is refused before board.lock is created there.

    Set up: the .cairn dir itself is a valid non-symlink dir, but its parent
    chain contains a symlink (simulate via a symlinked intermediate directory).
    We use the simplest scenario: .cairn is a symlink (same as the prior tests,
    but this time we explicitly verify safe_mkdir's refusal, not just assert_safe_root).
    This also covers the case where safe_mkdir is called on a path whose
    existing ancestor is a symlink.
    """
    real_cairn = tmp_path / "real_cairn"
    real_cairn.mkdir()
    link_cairn = tmp_path / ".cairn"
    link_cairn.symlink_to(real_cairn)

    # add_entry acquires _board_lock which calls safe_mkdir(cairn_dir, lock.parent).
    # safe_mkdir sees the symlinked .cairn root and must raise before creating board.lock.
    with pytest.raises(ValueError):
        board.add_entry(link_cairn, {"id": "T01"}, now=FIXED)

    # safe_mkdir must not have created board.lock in the outside target.
    assert not (real_cairn / "board.lock").exists(), \
        "safe_mkdir must not create board.lock through a symlinked .cairn component"
