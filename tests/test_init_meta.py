"""Tests for `cairn init` scaffolding .cairn/meta.json with the format version."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

from cairn_core import board, init  # noqa: E402

TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "cairn"


def test_scaffold_writes_meta_json_format_2(tmp_path):
    cairn = init.scaffold(tmp_path, "greenfield", TEMPLATES)
    meta = cairn / "meta.json"
    assert meta.exists()
    assert json.loads(meta.read_text()) == {"format": 2}
    # the stamp must track the canonical version constant
    assert board.FORMAT_VERSION == 2


def test_scaffold_meta_json_not_clobbered_on_reinit(tmp_path):
    cairn = init.scaffold(tmp_path, "greenfield", TEMPLATES)
    (cairn / "meta.json").write_text('{"format": 99}\n')
    init.scaffold(tmp_path, "greenfield", TEMPLATES)  # second run: idempotent
    assert json.loads((cairn / "meta.json").read_text()) == {"format": 99}
