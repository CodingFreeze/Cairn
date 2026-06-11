import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import vaultio

import pytest

FIXED = "2026-06-08T00:00:00+00:00"


def _vault(tmp_path):
    v = tmp_path / ".cairn" / "vault"
    v.mkdir(parents=True)
    (v / "decisions.md").write_text("# Decisions — append-only log\n\n_(empty)_\n")
    return tmp_path / ".cairn"


def test_resolve_vault_file_allows_known(tmp_path):
    cairn = _vault(tmp_path)
    p = vaultio.resolve_vault_file(cairn, "decisions")
    assert p.name == "decisions.md"


def test_resolve_vault_file_rejects_unknown(tmp_path):
    cairn = _vault(tmp_path)
    with pytest.raises(ValueError):
        vaultio.resolve_vault_file(cairn, "passwords")


def test_resolve_vault_file_rejects_traversal(tmp_path):
    cairn = _vault(tmp_path)
    with pytest.raises(ValueError):
        vaultio.resolve_vault_file(cairn, "../../etc/passwd")


def test_append_adds_timestamped_entry(tmp_path):
    cairn = _vault(tmp_path)
    vaultio.append(cairn, "decisions", "Chose flat-file vault", now=FIXED)
    text = (cairn / "vault" / "decisions.md").read_text()
    assert "Chose flat-file vault" in text
    assert FIXED in text
    assert text.startswith("# Decisions")  # header preserved, never clobbered


def test_append_never_clobbers_prior(tmp_path):
    cairn = _vault(tmp_path)
    vaultio.append(cairn, "decisions", "first", now=FIXED)
    vaultio.append(cairn, "decisions", "second", now=FIXED)
    text = (cairn / "vault" / "decisions.md").read_text()
    assert "first" in text and "second" in text
    assert text.index("first") < text.index("second")  # strictly appended


def test_append_creates_file_if_missing(tmp_path):
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    vaultio.append(cairn, "issues", "no header yet", now=FIXED)
    assert "no header yet" in (cairn / "vault" / "issues.md").read_text()


def test_append_is_idempotent_on_exact_duplicate(tmp_path):
    cairn = _vault(tmp_path)
    vaultio.append(cairn, "decisions", "dedupe me", now=FIXED, dedupe=True)
    vaultio.append(cairn, "decisions", "dedupe me", now=FIXED, dedupe=True)
    text = (cairn / "vault" / "decisions.md").read_text()
    assert text.count("dedupe me") == 1


def test_already_present_detects_substring(tmp_path):
    cairn = _vault(tmp_path)
    vaultio.append(cairn, "decisions", "auth uses JWT", now=FIXED)
    assert vaultio.already_present(cairn, "decisions", "auth uses JWT") is True
    assert vaultio.already_present(cairn, "decisions", "auth uses OAuth") is False


# --- symlink-traversal hardening (CRITICAL) ---

def test_append_refuses_symlinked_vault_file(tmp_path):
    """A malicious repo plants decisions.md as a symlink to an outside file.
    append() must refuse and leave the outside file UNCHANGED."""
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("ORIGINAL-OUTSIDE\n")
    link = cairn / "vault" / "decisions.md"
    link.symlink_to(outside)

    with pytest.raises(ValueError):
        vaultio.append(cairn, "decisions", "malicious append", now=FIXED)

    # The outside file must be untouched.
    assert outside.read_text() == "ORIGINAL-OUTSIDE\n"


def test_append_refuses_symlinked_vault_dir(tmp_path):
    """If the vault directory itself is a symlink escaping the cairn root, refuse."""
    cairn = tmp_path / ".cairn"
    cairn.mkdir(parents=True)
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    (cairn / "vault").symlink_to(outside_dir)

    with pytest.raises(ValueError):
        vaultio.append(cairn, "decisions", "malicious append via dir symlink", now=FIXED)


def test_append_symlinked_root_creates_no_outside_dir(tmp_path):
    """A symlinked .cairn root must be refused BEFORE any parent mkdir, so no
    'vault' directory is created through the symlink outside the repo."""
    real = tmp_path / "real_cairn"
    real.mkdir()
    link = tmp_path / ".cairn"
    link.symlink_to(real)

    with pytest.raises(ValueError):
        vaultio.append(link, "decisions", "malicious", now=FIXED)

    # The guard must fire BEFORE the parent mkdir — no vault/ dir created.
    assert not (real / "vault").exists()


def test_already_present_refuses_symlinked_vault_file(tmp_path):
    """dedupe read path must refuse a symlinked vault file (no leak via read)."""
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    outside = tmp_path / "secret.txt"
    outside.write_text("SECRET\n")
    (cairn / "vault" / "decisions.md").symlink_to(outside)
    with pytest.raises((ValueError, OSError)):
        vaultio.already_present(cairn, "decisions", "anything")


def test_append_dedupe_refuses_symlinked_vault_file(tmp_path):
    """append(dedupe=True) over a symlinked vault file → raises, no leak."""
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    outside = tmp_path / "secret.txt"
    outside.write_text("SECRET\n")
    (cairn / "vault" / "decisions.md").symlink_to(outside)
    with pytest.raises((ValueError, OSError)):
        vaultio.append(cairn, "decisions", "x", now=FIXED, dedupe=True)
    assert outside.read_text() == "SECRET\n"


# --- Fix 3: vault mkdir goes through safe_mkdir (symlinked vault component refused) ---

def test_append_symlinked_vault_component_mkdir_refused(tmp_path):
    """If vault/ doesn't exist yet but a planted symlink for vault/ is present,
    safe_mkdir must refuse and not create vault/ content in the outside target."""
    cairn = tmp_path / ".cairn"
    cairn.mkdir(parents=True)
    # Plant a symlink where vault/ would be created.
    outside_dir = tmp_path / "outside_vault_target"
    outside_dir.mkdir()
    (cairn / "vault").symlink_to(outside_dir)

    with pytest.raises(ValueError):
        vaultio.append(cairn, "decisions", "should not land outside", now=FIXED)

    # No file must have been created in the outside target via the symlink.
    assert not (outside_dir / "decisions.md").exists()
