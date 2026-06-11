"""Coverage for the .cairn/.gitattributes scaffold (team union-merge block)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import init

TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "cairn"


def test_scaffold_writes_gitattributes_block(tmp_path):
    cairn = init.scaffold(tmp_path, "greenfield", TEMPLATES)
    ga = (cairn / ".gitattributes").read_text()
    assert init._GA_BEGIN in ga and init._GA_END in ga
    assert "vault/*.md merge=union" in ga
    assert "handoff/*.md merge=union" in ga


def test_scaffold_gitattributes_board_not_union(tmp_path):
    """board.jsonl must NOT be union-merged: union would manufacture duplicate
    ticket ids, which read_board fails closed on. Conflicts must stay loud."""
    cairn = init.scaffold(tmp_path, "greenfield", TEMPLATES)
    rules = [
        line for line in (cairn / ".gitattributes").read_text().splitlines()
        if not line.lstrip().startswith("#") and "merge=union" in line
    ]
    assert rules, "expected at least the vault/handoff union rules"
    assert not any("board" in r for r in rules)


def test_scaffold_gitattributes_is_idempotent(tmp_path):
    cairn = init.scaffold(tmp_path, "greenfield", TEMPLATES)
    init.scaffold(tmp_path, "greenfield", TEMPLATES)  # second run
    ga = (cairn / ".gitattributes").read_text()
    assert ga.count(init._GA_BEGIN) == 1  # block added exactly once


def test_scaffold_gitattributes_appends_without_clobbering(tmp_path):
    cairn = tmp_path / ".cairn"
    cairn.mkdir()
    (cairn / ".gitattributes").write_text("tickets/*.md diff=markdown\n")
    init.scaffold(tmp_path, "existing", TEMPLATES)
    ga = (cairn / ".gitattributes").read_text()
    assert "tickets/*.md diff=markdown" in ga  # operator rules preserved
    assert init._GA_BEGIN in ga
    assert "vault/*.md merge=union" in ga


def test_scaffold_gitattributes_refuses_symlinked_leaf(tmp_path):
    """A planted symlinked .gitattributes must be refused, not written THROUGH;
    the outside file stays unchanged."""
    cairn = tmp_path / ".cairn"
    cairn.mkdir()
    outside = tmp_path / "outside_attrs"
    outside.write_text("ORIGINAL\n")
    (cairn / ".gitattributes").symlink_to(outside)
    with pytest.raises(ValueError):
        init.scaffold(tmp_path, "greenfield", TEMPLATES)
    assert outside.read_text() == "ORIGINAL\n"
