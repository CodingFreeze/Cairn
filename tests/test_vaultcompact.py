"""`cairn vault compact` — deterministic, LLM-free vault compaction."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import vaultcompact, vaultio

CLI = Path(__file__).resolve().parent.parent / "bin" / "cairn"
HEAD = "# Decisions — append-only log\n\n> Single-writer.\n"


def _seed(tmp_path, texts, name="decisions"):
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True, exist_ok=True)
    live = cairn / "vault" / f"{name}.md"
    if not live.exists():
        live.write_text(HEAD)
    for i, t in enumerate(texts):
        vaultio.append(cairn, name, t, now=f"2026-06-{i + 1:02d}T00:00:00+00:00")
    return cairn, live


def _bullets(path):
    return [l.strip() for l in path.read_text().splitlines()
            if l.lstrip().startswith("- ")]


# --- dedupe -----------------------------------------------------------------


def test_dedupes_exact_duplicate_bullets_keeps_first(tmp_path):
    cairn, live = _seed(tmp_path, ["alpha", "beta", "alpha"])
    # Make line 3 an EXACT duplicate of line 1 (same stamp + text).
    dup = _bullets(live)[0]
    text = live.read_text().splitlines()
    text[-1] = dup
    live.write_text("\n".join(text) + "\n")
    vaultcompact.run(cairn, "decisions", keep=50, apply=True)
    kept = _bullets(live)
    assert kept.count(dup) == 1
    assert kept[0] == dup  # first occurrence kept, in original position
    assert len(kept) == 2


# --- keep-N split -----------------------------------------------------------


def test_keep_n_moves_oldest_to_archive_keeps_newest_tail(tmp_path):
    cairn, live = _seed(tmp_path, ["one", "two", "three", "four", "five"])
    out = vaultcompact.run(cairn, "decisions", keep=2, apply=True)
    assert "3 archived, 2 kept" in out
    kept = _bullets(live)
    assert len(kept) == 2 and "four" in kept[0] and "five" in kept[1]
    arch = (cairn / "vault" / "archive" / "decisions-archive.md").read_text()
    for old in ("one", "two", "three"):
        assert old in arch
    assert "four" not in arch and "five" not in arch
    # Live file keeps its head and gains exactly one pointer line.
    text = live.read_text()
    assert text.startswith("# Decisions")
    assert text.count(vaultcompact._POINTER_PREFIX) == 1
    assert "archive/decisions-archive.md" in text


def test_pointer_not_duplicated_on_recompaction(tmp_path):
    cairn, live = _seed(tmp_path, [f"n{i}" for i in range(6)])
    vaultcompact.run(cairn, "decisions", keep=3, apply=True)
    vaultio.append(cairn, "decisions", "later", now="2026-07-01T00:00:00+00:00")
    vaultcompact.run(cairn, "decisions", keep=3, apply=True)
    assert live.read_text().count(vaultcompact._POINTER_PREFIX) == 1


# --- archive append-not-clobber ----------------------------------------------


def test_archive_appends_never_clobbers(tmp_path):
    cairn, _ = _seed(tmp_path, ["one", "two", "three"])
    vaultcompact.run(cairn, "decisions", keep=2, apply=True,
                     now="2026-06-09T00:00:00+00:00")
    vaultio.append(cairn, "decisions", "four", now="2026-06-20T00:00:00+00:00")
    vaultcompact.run(cairn, "decisions", keep=2, apply=True,
                     now="2026-06-10T00:00:00+00:00")
    arch = (cairn / "vault" / "archive" / "decisions-archive.md").read_text()
    assert "one" in arch and "two" in arch  # both compactions survive
    assert arch.count("## Compacted") == 2  # timestamped header per run
    assert "2026-06-09" in arch and "2026-06-10" in arch


# --- dry-run ------------------------------------------------------------------


def test_dry_run_writes_nothing(tmp_path):
    cairn, live = _seed(tmp_path, ["one", "two", "three"])
    before = live.read_text()
    out = vaultcompact.run(cairn, "decisions", keep=1, apply=False)
    assert "dry-run" in out and "2 archived, 1 kept" in out
    assert live.read_text() == before  # live file untouched
    assert not (cairn / "vault" / "archive").exists()  # no archive created


def test_nothing_to_compact_is_a_noop_even_with_apply(tmp_path):
    cairn, live = _seed(tmp_path, ["one", "two"])
    before = live.read_text()
    out = vaultcompact.run(cairn, "decisions", keep=50, apply=True)
    assert "nothing to compact" in out
    assert live.read_text() == before


# --- rejection ----------------------------------------------------------------


def test_unknown_vault_name_rejected(tmp_path):
    cairn, _ = _seed(tmp_path, ["one"])
    with pytest.raises(ValueError, match="unknown vault file"):
        vaultcompact.run(cairn, "secrets", keep=1)
    with pytest.raises(ValueError, match="unknown vault file"):
        vaultcompact.run(cairn, "../../etc/passwd", keep=1)


def test_negative_keep_rejected(tmp_path):
    cairn, _ = _seed(tmp_path, ["one"])
    with pytest.raises(ValueError, match="non-negative"):
        vaultcompact.run(cairn, "decisions", keep=-1)


# --- CLI wiring ----------------------------------------------------------------


def _run_cli(args, cwd):
    return subprocess.run([sys.executable, str(CLI), *args],
                          cwd=cwd, capture_output=True, text=True)


def test_cli_vault_compact_dry_run_then_apply(tmp_path):
    _seed(tmp_path, ["one", "two", "three"])
    r = _run_cli(["vault", "compact", "decisions", "--keep", "1"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "dry-run" in r.stdout
    r = _run_cli(["vault", "compact", "decisions", "--keep", "1", "--apply"],
                 tmp_path)
    assert r.returncode == 0, r.stderr
    assert "applied" in r.stdout
    assert (tmp_path / ".cairn" / "vault" / "archive" /
            "decisions-archive.md").exists()


def test_cli_vault_compact_unknown_name_errors(tmp_path):
    _seed(tmp_path, ["one"])
    r = _run_cli(["vault", "compact", "nope", "--apply"], tmp_path)
    assert r.returncode != 0
    assert "unknown vault file" in r.stderr
