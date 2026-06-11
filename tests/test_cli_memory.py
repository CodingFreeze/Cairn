import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parent.parent / "bin" / "cairn"


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=cwd, capture_output=True, text=True,
    )


def _init(tmp_path):
    r = _run(["init", "--greenfield"], tmp_path)
    assert r.returncode == 0, r.stderr


def test_vault_append_writes_entry(tmp_path):
    _init(tmp_path)
    r = _run(["vault", "append", "decisions", "Chose flat-file vault as source of truth"], tmp_path)
    assert r.returncode == 0, r.stderr
    text = (tmp_path / ".cairn" / "vault" / "decisions.md").read_text()
    assert "Chose flat-file vault as source of truth" in text


def test_vault_append_rejects_unknown_file(tmp_path):
    _init(tmp_path)
    r = _run(["vault", "append", "passwords", "secret"], tmp_path)
    assert r.returncode != 0
    assert "unknown vault file" in (r.stderr + r.stdout).lower()


def test_handoff_writes_latest(tmp_path):
    _init(tmp_path)
    _run(["board", "add", '{"id": "T01"}'], tmp_path)
    r = _run(["handoff"], tmp_path)
    assert r.returncode == 0, r.stderr
    latest = tmp_path / ".cairn" / "handoff" / "latest.md"
    assert latest.exists()
    assert "Cairn Handoff" in latest.read_text()
    assert "T01" in latest.read_text()


def test_recall_greps_vault(tmp_path):
    _init(tmp_path)
    _run(["vault", "append", "decisions", "Auth uses JWT with short-lived access tokens"], tmp_path)
    r = _run(["recall", "auth"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "JWT" in r.stdout


def test_recall_no_match_reports_cleanly(tmp_path):
    _init(tmp_path)
    r = _run(["recall", "nonexistent-topic-xyz"], tmp_path)
    assert r.returncode == 0
    assert "no matches" in r.stdout.lower()


import json


def test_dismiss_harvests_durable_only(tmp_path):
    _init(tmp_path)
    cands = [
        {"kind": "decisions", "text": "We decided to use Postgres for the index"},
        {"kind": "decisions", "text": "ok thanks"},               # chatter -> dropped
        {"kind": "issues", "text": "CI fails on tz; remedy: pin UTC in tests"},
        {"kind": "gossip", "text": "this is some long durable-looking sentence"},  # bad kind
    ]
    r = _run(["dismiss", json.dumps(cands)], tmp_path)
    assert r.returncode == 0, r.stderr
    decisions = (tmp_path / ".cairn" / "vault" / "decisions.md").read_text()
    issues = (tmp_path / ".cairn" / "vault" / "issues.md").read_text()
    assert "Postgres for the index" in decisions
    assert "ok thanks" not in decisions
    assert "pin UTC in tests" in issues
    assert "gossip" not in (decisions + issues)


def test_dismiss_does_not_duplicate_existing(tmp_path):
    _init(tmp_path)
    _run(["vault", "append", "decisions", "Auth uses JWT with short-lived tokens"], tmp_path)
    cands = [{"kind": "decisions", "text": "Auth uses JWT with short-lived tokens"}]
    r = _run(["dismiss", json.dumps(cands)], tmp_path)
    assert r.returncode == 0, r.stderr
    decisions = (tmp_path / ".cairn" / "vault" / "decisions.md").read_text()
    assert decisions.count("Auth uses JWT with short-lived tokens") == 1


def test_dismiss_rebuilds_handoff(tmp_path):
    _init(tmp_path)
    cands = [{"kind": "decisions", "text": "We decided to ship the memory layer first"}]
    r = _run(["dismiss", json.dumps(cands)], tmp_path)
    assert r.returncode == 0, r.stderr
    latest = tmp_path / ".cairn" / "handoff" / "latest.md"
    assert latest.exists()
    assert "Cairn Handoff" in latest.read_text()


def test_dismiss_reports_capture_log(tmp_path):
    _init(tmp_path)
    cands = [{"kind": "decisions", "text": "We chose flat-file memory as the moat"}]
    r = _run(["dismiss", json.dumps(cands)], tmp_path)
    assert "captured" in r.stdout.lower()
    assert "decisions" in r.stdout


def test_dismiss_rejects_non_array_json(tmp_path):
    _init(tmp_path)
    r = _run(["dismiss", "{}"], tmp_path)
    assert r.returncode != 0
    assert "error" in (r.stderr + r.stdout).lower()
    assert "Traceback" not in r.stderr


def test_dismiss_rejects_non_dict_items(tmp_path):
    _init(tmp_path)
    r = _run(["dismiss", '["x"]'], tmp_path)
    assert r.returncode != 0
    assert "error" in (r.stderr + r.stdout).lower()
    assert "Traceback" not in r.stderr


def test_recall_symlinked_vault_file_raises_error(tmp_path):
    """vault/decisions.md symlinked to an outside file → recall must fail with
    returncode != 0, 'error' in output, no Traceback, and the outside file
    content must NOT appear in output."""
    _init(tmp_path)
    cairn = tmp_path / ".cairn"
    outside = tmp_path / "outside_secret.txt"
    # Write a file with bullet-formatted content that would match the recall
    # query if read and printed (proves the read path is guarded, not just the
    # write path).
    outside.write_text("- SUPER SECRET recall-me CONTENTS\n")
    vault_file = cairn / "vault" / "decisions.md"
    vault_file.unlink(missing_ok=True)
    vault_file.symlink_to(outside)

    r = _run(["recall", "recall-me"], tmp_path)

    assert r.returncode != 0, "expected non-zero returncode for symlinked vault file"
    combined = r.stdout + r.stderr
    assert "error" in combined.lower(), f"expected 'error' in output, got: {combined!r}"
    assert "Traceback" not in r.stderr, "must not expose traceback"
    assert "SUPER SECRET" not in combined, "must not leak outside file contents"


def test_dismiss_symlinked_vault_file_raises_error(tmp_path):
    """vault/decisions.md symlinked to an outside file → dismiss must fail with
    returncode != 0, 'error' in output, no Traceback, and the outside file
    must be unchanged."""
    _init(tmp_path)
    cairn = tmp_path / ".cairn"
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("OUTSIDE ORIGINAL CONTENT\n")
    vault_file = cairn / "vault" / "decisions.md"
    vault_file.unlink(missing_ok=True)
    vault_file.symlink_to(outside)

    cands = [{"kind": "decisions", "text": "We chose to use Postgres"}]
    r = _run(["dismiss", json.dumps(cands)], tmp_path)

    assert r.returncode != 0, "expected non-zero returncode for symlinked vault file"
    combined = r.stdout + r.stderr
    assert "error" in combined.lower(), f"expected 'error' in output, got: {combined!r}"
    assert "Traceback" not in r.stderr, "must not expose traceback"
    assert outside.read_text() == "OUTSIDE ORIGINAL CONTENT\n", "outside file must be unchanged"


# --- Fix 2: recall/dismiss reads go through safe_open_read (O_NOFOLLOW, TOCTOU) ---

def test_recall_onofollow_blocks_symlinked_component(tmp_path):
    """recall reads vault files via safe_open_read (O_NOFOLLOW): a symlink planted
    as a vault file component is refused at the kernel level and content is not
    returned to output (guards the TOCTOU gap between check and open)."""
    _init(tmp_path)
    cairn = tmp_path / ".cairn"
    outside = tmp_path / "onofollow_secret.txt"
    # Use bullet-prefixed content so it would match recall if the read succeeded.
    outside.write_text("- onofollow-probe LEAKED\n")
    vault_file = cairn / "vault" / "schema.md"
    vault_file.unlink(missing_ok=True)
    vault_file.symlink_to(outside)

    r = _run(["recall", "onofollow-probe"], tmp_path)

    # O_NOFOLLOW must refuse the symlinked file — either the process exits with
    # error or the content is silently skipped; either way the secret must not leak.
    assert "onofollow-probe LEAKED" not in (r.stdout + r.stderr), \
        "safe_open_read (O_NOFOLLOW) must not leak outside file contents"


def test_dismiss_existing_read_uses_onofollow(tmp_path):
    """dismiss reads existing vault files for dedup via safe_open_read (O_NOFOLLOW):
    a symlinked vault file is refused and the outside content does not appear in
    the captured output (TOCTOU gap closed at the kernel open call)."""
    _init(tmp_path)
    cairn = tmp_path / ".cairn"
    outside = tmp_path / "dismiss_onofollow_secret.txt"
    outside.write_text("dismiss-onofollow-probe SECRET\n")
    vault_file = cairn / "vault" / "issues.md"
    vault_file.unlink(missing_ok=True)
    vault_file.symlink_to(outside)

    cands = [{"kind": "decisions", "text": "safe architecture decision"}]
    r = _run(["dismiss", json.dumps(cands)], tmp_path)

    # The outside file must not be read/surfaced; process may exit non-zero.
    assert "dismiss-onofollow-probe SECRET" not in (r.stdout + r.stderr), \
        "safe_open_read (O_NOFOLLOW) must not leak outside file contents via dismiss"


# --- Finding 1: harvest-candidates subcommand (safe read + delete via CLI) ---

def test_harvest_candidates_processes_and_deletes_file(tmp_path):
    """harvest-candidates with a normal candidates file: appends fact to vault and
    deletes the staging file; returns rc 0."""
    _init(tmp_path)
    cairn = tmp_path / ".cairn"
    cand = cairn / "handoff" / "dismiss-candidates.json"
    cands = [{"kind": "decisions", "text": "We decided to use Postgres for storage"}]
    cand.write_text(json.dumps(cands))

    r = _run(["harvest-candidates"], tmp_path)

    assert r.returncode == 0, r.stderr
    # Durable fact must be appended to the vault.
    decisions = (cairn / "vault" / "decisions.md").read_text()
    assert "Postgres for storage" in decisions
    # The staging file must be removed after harvest.
    assert not cand.exists(), "harvest-candidates must delete the candidates file after processing"


def test_harvest_candidates_symlinked_handoff_parent_refuses(tmp_path):
    """harvest-candidates with .cairn/handoff as a symlink to an outside dir:
    CLI must refuse (rc != 0, 'error' in output, no Traceback), the outside
    file must NOT be read into the vault, and must NOT be deleted."""
    _init(tmp_path)
    cairn = tmp_path / ".cairn"
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    outside_cand = outside_dir / "dismiss-candidates.json"
    cands = [{"kind": "decisions", "text": "We decided to use Postgres for storage"}]
    outside_cand.write_text(json.dumps(cands))

    # Replace .cairn/handoff with a symlink to the outside dir.
    import shutil
    shutil.rmtree(str(cairn / "handoff"), ignore_errors=True)
    (cairn / "handoff").symlink_to(outside_dir)

    r = _run(["harvest-candidates"], tmp_path)

    assert r.returncode != 0, "expected non-zero rc when handoff parent is a symlink"
    combined = r.stdout + r.stderr
    assert "error" in combined.lower(), f"expected 'error' in output, got: {combined!r}"
    assert "Traceback" not in r.stderr, "must not expose traceback"
    # Outside file must NOT be read into the vault.
    decisions_file = cairn / "vault" / "decisions.md"
    if decisions_file.exists():
        assert "Postgres for storage" not in decisions_file.read_text(), \
            "outside file content must not be harvested into vault"
    # Outside file must NOT be deleted.
    assert outside_cand.exists(), "harvest-candidates must not delete outside file"


def test_harvest_candidates_no_file_exits_zero_silently(tmp_path):
    """harvest-candidates with no staging file: rc 0, no output."""
    _init(tmp_path)

    r = _run(["harvest-candidates"], tmp_path)

    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "", f"expected no output, got: {r.stdout!r}"
    assert r.stderr.strip() == "", f"expected no stderr, got: {r.stderr!r}"
