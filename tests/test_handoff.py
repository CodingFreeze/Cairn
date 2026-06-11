import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import handoff


def _setup(tmp_path):
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    (cairn / "handoff").mkdir()
    (cairn / "tickets").mkdir()
    (cairn / "board.jsonl").write_text(
        '{"id": "T01", "status": "merged", "depends_on": []}\n'
        '{"id": "T02", "status": "in-progress", "branch": "cairn/T02", "depends_on": ["T01"]}\n'
        '{"id": "T03", "status": "todo", "depends_on": ["T02"]}\n'
    )
    (cairn / "vault" / "decisions.md").write_text(
        "# Decisions\n\n- 2026-06-08T00:00:00+00:00 — Chose flat-file vault\n"
    )
    (cairn / "vault" / "issues.md").write_text(
        "# Issues\n\n- 2026-06-08T00:00:00+00:00 — tests flaky on CI; remedy: pin tz\n"
    )
    (cairn / "tickets" / "T02.md").write_text("# T02\nGoal: build login\n")
    return cairn


def test_build_includes_board_summary(tmp_path):
    cairn = _setup(tmp_path)
    pack = handoff.build_pack(cairn)
    assert "T01" in pack and "merged" in pack
    assert "T02" in pack and "in-progress" in pack
    assert "T03" in pack and "todo" in pack


def test_build_lists_open_tickets(tmp_path):
    cairn = _setup(tmp_path)
    pack = handoff.build_pack(cairn)
    # merged ticket should NOT appear under open work
    open_section = pack.split("## Open tickets", 1)[1]
    assert "T02" in open_section and "T03" in open_section
    assert "T01" not in open_section


def test_build_includes_recent_decisions_and_issues(tmp_path):
    cairn = _setup(tmp_path)
    pack = handoff.build_pack(cairn)
    assert "Chose flat-file vault" in pack
    assert "tests flaky on CI" in pack


def test_build_handles_empty_vault(tmp_path):
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    (cairn / "board.jsonl").write_text("")
    pack = handoff.build_pack(cairn)
    assert "Cairn Handoff" in pack
    assert "No tickets" in pack


def test_write_pack_writes_latest(tmp_path):
    cairn = _setup(tmp_path)
    p = handoff.write_pack(cairn)
    assert p == cairn / "handoff" / "latest.md"
    assert "Cairn Handoff" in p.read_text()


def test_recent_tail_returns_last_n(tmp_path):
    lines = "\n".join(f"- entry {i}" for i in range(10))
    tail = handoff.recent_tail(lines, n=3)
    assert "entry 9" in tail and "entry 7" in tail
    assert "entry 6" not in tail


import pytest


def test_write_pack_refuses_symlinked_latest(tmp_path):
    """latest.md planted as a symlink to an outside file → write_pack must refuse
    and the outside file must be UNCHANGED."""
    cairn = _setup(tmp_path)
    outside = tmp_path / "outside_target.txt"
    outside.write_text("ORIGINAL-OUTSIDE\n")
    latest = cairn / "handoff" / "latest.md"
    latest.symlink_to(outside)

    with pytest.raises(ValueError):
        handoff.write_pack(cairn)

    assert outside.read_text() == "ORIGINAL-OUTSIDE\n"


def test_read_vault_skips_symlinked_source(tmp_path):
    """A symlinked vault source file is refused/skipped, not followed outside."""
    cairn = _setup(tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("SECRET-CONTENTS leaked\n")
    (cairn / "vault" / "decisions.md").unlink()
    (cairn / "vault" / "decisions.md").symlink_to(outside)
    pack = handoff.build_pack(cairn)
    assert "SECRET-CONTENTS" not in pack


def test_board_symlink_raises_and_does_not_leak(tmp_path):
    """board.jsonl planted as symlink to outside file → build_pack raises ValueError;
    outside file content must NOT appear in any output."""
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    (cairn / "handoff").mkdir()
    (cairn / "tickets").mkdir()
    outside = tmp_path / "outside_board.txt"
    outside.write_text(
        '{"id": "EVIL", "status": "todo", "depends_on": []}\n'
    )
    # Plant board.jsonl as a symlink to the outside file.
    (cairn / "board.jsonl").symlink_to(outside)

    with pytest.raises(ValueError):
        handoff.build_pack(cairn)

    # The outside file must be untouched.
    assert outside.read_text() == '{"id": "EVIL", "status": "todo", "depends_on": []}\n'


def test_write_pack_symlinked_root_creates_no_outside_dir(tmp_path):
    """A symlinked .cairn root must be refused BEFORE the handoff/ mkdir, so no
    handoff directory is created through the symlink outside the repo."""
    real = tmp_path / "real_cairn"
    (real / "vault").mkdir(parents=True)
    (real / "board.jsonl").write_text("")
    link = tmp_path / ".cairn"
    link.symlink_to(real)

    with pytest.raises(ValueError):
        handoff.write_pack(link)

    # The guard must fire BEFORE the mkdir — no handoff/ dir created.
    assert not (real / "handoff").exists()


# --- Fix 3: handoff/ mkdir goes through safe_mkdir (symlinked handoff component refused) ---

def test_write_pack_symlinked_handoff_component_mkdir_refused(tmp_path):
    """If handoff/ doesn't exist yet but a planted symlink for handoff/ is present,
    safe_mkdir must refuse and not create files in the outside target."""
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    (cairn / "board.jsonl").write_text("")
    # Plant a symlink where handoff/ would be created.
    outside_dir = tmp_path / "outside_handoff_target"
    outside_dir.mkdir()
    (cairn / "handoff").symlink_to(outside_dir)

    with pytest.raises(ValueError):
        handoff.write_pack(cairn)

    # No file must have been created in the outside target via the symlink.
    assert not (outside_dir / "latest.md").exists()
