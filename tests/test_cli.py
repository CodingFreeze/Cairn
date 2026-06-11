import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parent.parent / "bin" / "cairn"


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=cwd, capture_output=True, text=True,
    )


def test_init_then_add_next_status_flow(tmp_path):
    r = _run(["init", "--greenfield"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / ".cairn" / "board.jsonl").exists()

    r = _run(["board", "add", '{"id": "T01"}'], tmp_path)
    assert r.returncode == 0, r.stderr

    r = _run(["board", "add", '{"id": "T02", "depends_on": ["T01"]}'], tmp_path)
    assert r.returncode == 0, r.stderr

    # T01 ready (no deps); T02 blocked
    r = _run(["next"], tmp_path)
    assert r.stdout.strip() == "T01"

    # merge T01 -> T02 becomes ready
    r = _run(["board", "set", "T01", "status=merged"], tmp_path)
    assert r.returncode == 0, r.stderr
    r = _run(["next"], tmp_path)
    assert r.stdout.strip() == "T02"

    r = _run(["status"], tmp_path)
    assert "T01" in r.stdout and "T02" in r.stdout


def test_commands_error_without_cairn_dir(tmp_path):
    r = _run(["status"], tmp_path)
    assert r.returncode != 0
    assert "no .cairn" in (r.stderr + r.stdout).lower()


def test_init_autodetects_existing(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    r = _run(["init"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / ".cairn" / ".mode").read_text().strip() == "existing"


# --- CLI negative tests ---

def _init_board(tmp_path):
    """Helper: init a board and return tmp_path."""
    _run(["init", "--greenfield"], tmp_path)
    return tmp_path


def test_cli_bad_json_payload(tmp_path):
    _init_board(tmp_path)
    r = _run(["board", "add", "NOT_JSON"], tmp_path)
    assert r.returncode != 0
    assert "error" in (r.stderr + r.stdout).lower()
    assert "Traceback" not in r.stderr


def test_cli_payload_missing_id(tmp_path):
    _init_board(tmp_path)
    r = _run(["board", "add", '{"status": "todo"}'], tmp_path)
    assert r.returncode != 0
    assert "error" in (r.stderr + r.stdout).lower()
    assert "Traceback" not in r.stderr


def test_cli_duplicate_id(tmp_path):
    _init_board(tmp_path)
    _run(["board", "add", '{"id": "T01"}'], tmp_path)
    r = _run(["board", "add", '{"id": "T01"}'], tmp_path)
    assert r.returncode != 0
    assert "error" in (r.stderr + r.stdout).lower()
    assert "Traceback" not in r.stderr


def test_cli_set_unknown_id(tmp_path):
    _init_board(tmp_path)
    r = _run(["board", "set", "T99", "status=todo"], tmp_path)
    assert r.returncode != 0
    assert "error" in (r.stderr + r.stdout).lower()
    assert "Traceback" not in r.stderr


def test_cli_set_arg_without_equals(tmp_path):
    _init_board(tmp_path)
    _run(["board", "add", '{"id": "T01"}'], tmp_path)
    r = _run(["board", "set", "T01", "statusmerged"], tmp_path)
    assert r.returncode != 0
    assert "error" in (r.stderr + r.stdout).lower()
    assert "Traceback" not in r.stderr


def test_cli_set_reserved_field_id(tmp_path):
    _init_board(tmp_path)
    _run(["board", "add", '{"id": "T01"}'], tmp_path)
    r = _run(["board", "set", "T01", "id=T99"], tmp_path)
    assert r.returncode != 0
    assert "error" in (r.stderr + r.stdout).lower()
    assert "Traceback" not in r.stderr


# --- symlink-traversal hardening (CRITICAL) ---

def test_cli_refuses_symlinked_cairn_root(tmp_path):
    """A malicious repo ships .cairn as a symlink to an outside dir. The auto-running
    CLI must refuse cleanly (rc!=0, 'error', no Traceback) and never operate on it."""
    real = tmp_path / "real_cairn"
    (real / "vault").mkdir(parents=True)
    (real / "board.jsonl").write_text("")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".cairn").symlink_to(real)

    r = _run(["status"], repo)
    assert r.returncode != 0
    assert "error" in (r.stderr + r.stdout).lower()
    assert "Traceback" not in r.stderr
