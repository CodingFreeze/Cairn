"""`cairn board doctor` — repair of team-merge damage to board.jsonl."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import board, boarddoctor

CLI = Path(__file__).resolve().parent.parent / "bin" / "cairn"


def _entry(tid, status="todo", updated="2026-01-01T00:00:00+00:00", **kw):
    e = {"id": tid, "status": status, "branch": None, "pr": None,
         "depends_on": [], "owner": None, "files_owned": [], "updated": updated}
    e.update(kw)
    return e


def _write_board(tmp_path, lines):
    cairn = tmp_path / ".cairn"
    cairn.mkdir(exist_ok=True)
    (cairn / "board.jsonl").write_text(
        "".join((l if isinstance(l, str) else json.dumps(l)) + "\n"
                for l in lines))
    return cairn


# --- diagnose -------------------------------------------------------------


def test_clean_board_diagnoses_clean(tmp_path):
    cairn = _write_board(tmp_path, [_entry("T01"), _entry("T02")])
    diag = boarddoctor.diagnose(cairn)
    assert [e["id"] for e in diag["keep"]] == ["T01", "T02"]
    assert diag["dropped"] == [] and diag["quarantined"] == []


def test_duplicate_keeps_newest_by_updated(tmp_path):
    # The NEWER entry comes FIRST in file order: position must not win.
    cairn = _write_board(tmp_path, [
        _entry("T01", status="merged", updated="2026-06-02T00:00:00+00:00"),
        _entry("T01", status="todo", updated="2026-06-01T00:00:00+00:00"),
    ])
    diag = boarddoctor.diagnose(cairn)
    assert len(diag["keep"]) == 1
    assert diag["keep"][0]["status"] == "merged"
    assert len(diag["dropped"]) == 1
    lineno, line, reason = diag["dropped"][0]
    assert lineno == 2 and "duplicate id 'T01'" in reason and "todo" in line


def test_duplicate_tie_or_missing_updated_keeps_later_line(tmp_path):
    e1 = _entry("T01", status="todo"); del e1["updated"]
    e2 = _entry("T01", status="in-progress"); del e2["updated"]
    cairn = _write_board(tmp_path, [e1, e2])
    diag = boarddoctor.diagnose(cairn)
    assert diag["keep"][0]["status"] == "in-progress"
    assert diag["dropped"][0][0] == 1  # the earlier line is the one dropped


def test_malformed_lines_are_quarantined(tmp_path):
    cairn = _write_board(tmp_path, [
        _entry("T01"),
        "<<<<<<< HEAD",                      # conflict-marker debris
        '{"id": "T02", "status": "tod',      # truncated JSON
        '{"id": "../evil", "status": "todo"}',  # fails read-side validation
    ])
    diag = boarddoctor.diagnose(cairn)
    assert [e["id"] for e in diag["keep"]] == ["T01"]
    assert [lineno for lineno, _, _ in diag["quarantined"]] == [2, 3, 4]


def test_missing_board_is_clean(tmp_path):
    cairn = tmp_path / ".cairn"
    cairn.mkdir()
    diag = boarddoctor.diagnose(cairn)
    assert diag == {"keep": [], "dropped": [], "quarantined": []}


# --- dry-run vs apply ------------------------------------------------------


def test_dry_run_writes_nothing(tmp_path):
    cairn = _write_board(tmp_path, [_entry("T01"), "not json", _entry("T01")])
    before = (cairn / "board.jsonl").read_text()
    out = boarddoctor.run(cairn, apply=False)
    assert "dry-run" in out
    assert (cairn / "board.jsonl").read_text() == before  # untouched
    assert not (cairn / boarddoctor.REJ_FILENAME).exists()  # no quarantine file


def test_apply_repairs_and_quarantines(tmp_path):
    cairn = _write_board(tmp_path, [
        _entry("T01", status="todo", updated="2026-06-01T00:00:00+00:00"),
        "<<<<<<< HEAD",
        _entry("T01", status="merged", updated="2026-06-02T00:00:00+00:00"),
    ])
    out = boarddoctor.run(cairn, apply=True)
    assert "applied" in out
    # The repaired board is readable by the fail-closed reader again.
    entries = board.read_board(cairn)
    assert len(entries) == 1 and entries[0]["status"] == "merged"
    rej = (cairn / boarddoctor.REJ_FILENAME).read_text()
    assert "<<<<<<< HEAD" in rej and "quarantined by `cairn board doctor`" in rej


def test_apply_appends_rej_never_clobbers(tmp_path):
    cairn = _write_board(tmp_path, ["garbage one"])
    boarddoctor.run(cairn, apply=True, now="2026-06-09T00:00:00+00:00")
    _write_board(tmp_path, [_entry("T01"), "garbage two"])
    boarddoctor.run(cairn, apply=True, now="2026-06-10T00:00:00+00:00")
    rej = (cairn / boarddoctor.REJ_FILENAME).read_text()
    assert "garbage one" in rej and "garbage two" in rej  # both runs survive
    assert rej.count("quarantined by `cairn board doctor`") == 2


def test_apply_on_clean_board_is_a_noop(tmp_path):
    cairn = _write_board(tmp_path, [_entry("T01")])
    before = (cairn / "board.jsonl").read_text()
    out = boarddoctor.run(cairn, apply=True)
    assert "clean" in out
    assert (cairn / "board.jsonl").read_text() == before  # byte-untouched
    assert not (cairn / boarddoctor.REJ_FILENAME).exists()


# --- CLI wiring ------------------------------------------------------------


def _run_cli(args, cwd):
    return subprocess.run([sys.executable, str(CLI), *args],
                          cwd=cwd, capture_output=True, text=True)


def test_cli_board_doctor_dry_run_then_apply(tmp_path):
    _write_board(tmp_path, [
        _entry("T01", status="todo", updated="2026-06-01T00:00:00+00:00"),
        _entry("T01", status="merged", updated="2026-06-02T00:00:00+00:00"),
    ])
    r = _run_cli(["board", "doctor"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "1 duplicate(s) dropped" in r.stdout and "dry-run" in r.stdout
    # A duplicated board fails closed for normal reads...
    assert _run_cli(["board", "list"], tmp_path).returncode != 0
    # ...until doctor --apply repairs it.
    r = _run_cli(["board", "doctor", "--apply"], tmp_path)
    assert r.returncode == 0, r.stderr
    r = _run_cli(["board", "list"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)[0]["status"] == "merged"
