import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import init

TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "cairn"


def test_detect_greenfield_empty_dir(tmp_path):
    assert init.detect_mode(tmp_path) == "greenfield"


def test_detect_existing_with_git(tmp_path):
    (tmp_path / ".git").mkdir()
    assert init.detect_mode(tmp_path) == "existing"


def test_detect_existing_with_manifest(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    assert init.detect_mode(tmp_path) == "existing"


def test_detect_existing_with_src_dir(tmp_path):
    (tmp_path / "src").mkdir()
    assert init.detect_mode(tmp_path) == "existing"


def test_scaffold_creates_tree(tmp_path):
    cairn = init.scaffold(tmp_path, "greenfield", TEMPLATES)
    assert (cairn / "board.jsonl").exists()
    assert (cairn / "PROTOCOL.md").exists()
    assert (cairn / "vault" / "map.md").exists()
    assert (cairn / "tickets").is_dir()
    assert (cairn / "handoff").is_dir()
    assert (cairn / "spec").is_dir()
    assert (cairn / ".mode").read_text().strip() == "greenfield"


def test_scaffold_is_idempotent_no_clobber(tmp_path):
    cairn = init.scaffold(tmp_path, "greenfield", TEMPLATES)
    (cairn / "vault" / "decisions.md").write_text("MY DATA")
    init.scaffold(tmp_path, "greenfield", TEMPLATES)  # second run
    assert (cairn / "vault" / "decisions.md").read_text() == "MY DATA"


# --- .gitignore scaffold + goal persistence (bugs #12, #3) ---


def test_scaffold_writes_gitignore_block(tmp_path):
    init.scaffold(tmp_path, "greenfield", TEMPLATES)
    gi = (tmp_path / ".gitignore").read_text()
    assert init._GI_BEGIN in gi and init._GI_END in gi
    # The exact junk that derailed the dogfood merge must be ignored.
    assert ".cairn/worktrees/" in gi
    assert "__pycache__/" in gi
    assert "*.py[cod]" in gi


def test_scaffold_gitignore_is_idempotent(tmp_path):
    init.scaffold(tmp_path, "greenfield", TEMPLATES)
    init.scaffold(tmp_path, "greenfield", TEMPLATES)  # second run
    gi = (tmp_path / ".gitignore").read_text()
    assert gi.count(init._GI_BEGIN) == 1  # block added exactly once


def test_scaffold_gitignore_appends_without_clobbering(tmp_path):
    (tmp_path / ".gitignore").write_text("mystuff/\n*.log\n")
    init.scaffold(tmp_path, "existing", TEMPLATES)
    gi = (tmp_path / ".gitignore").read_text()
    assert "mystuff/" in gi and "*.log" in gi  # operator rules preserved
    assert init._GI_BEGIN in gi


def test_scaffold_gitignore_stack_extra_only_when_manifest(tmp_path):
    (tmp_path / "Cargo.toml").write_text('[package]\nname="x"\n')
    init.scaffold(tmp_path, "existing", TEMPLATES)
    assert "/target/" in (tmp_path / ".gitignore").read_text()


def test_scaffold_gitignore_refuses_symlink(tmp_path):
    """A symlinked .gitignore must not be followed (could redirect outside repo)."""
    outside = tmp_path / "outside_ignore"
    outside.write_text("ORIGINAL\n")
    link = tmp_path / "repo"
    link.mkdir()
    (link / ".gitignore").symlink_to(outside)
    init.scaffold(link, "greenfield", TEMPLATES)  # must not raise, must not write through
    assert outside.read_text() == "ORIGINAL\n"


def test_scaffold_persists_goal_to_vault(tmp_path):
    cairn = init.scaffold(tmp_path, "greenfield", TEMPLATES, goal="Build a tip calculator")
    goal = (cairn / "vault" / "goal.md").read_text()
    assert "Build a tip calculator" in goal


def test_scaffold_no_goal_file_when_goal_absent(tmp_path):
    cairn = init.scaffold(tmp_path, "greenfield", TEMPLATES)
    assert not (cairn / "vault" / "goal.md").exists()


def test_scaffold_goal_not_clobbered_on_reinit(tmp_path):
    cairn = init.scaffold(tmp_path, "greenfield", TEMPLATES, goal="ORIGINAL GOAL")
    init.scaffold(tmp_path, "greenfield", TEMPLATES, goal="DIFFERENT GOAL")
    assert "ORIGINAL GOAL" in (cairn / "vault" / "goal.md").read_text()


# --- symlink-traversal hardening (CRITICAL) ---

import pytest


def test_scaffold_refuses_symlinked_cairn_root(tmp_path):
    """A pre-existing symlinked .cairn root → scaffold refuses to operate."""
    real = tmp_path / "real_cairn"
    real.mkdir()
    (tmp_path / ".cairn").symlink_to(real)
    with pytest.raises(ValueError):
        init.scaffold(tmp_path, "greenfield", TEMPLATES)


def test_scaffold_refuses_symlinked_template_leaf(tmp_path):
    """A planted symlinked leaf (vault/map.md → outside) must be refused, not
    written THROUGH; the outside file stays unchanged."""
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("ORIGINAL-OUTSIDE\n")
    (cairn / "vault" / "map.md").symlink_to(outside)
    with pytest.raises(ValueError):
        init.scaffold(tmp_path, "greenfield", TEMPLATES)
    # The outside file must be untouched.
    assert outside.read_text() == "ORIGINAL-OUTSIDE\n"
