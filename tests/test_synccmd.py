"""GitHub Issues <-> board sync tests. ALL gh interaction is mocked.

No test here ever invokes the real `gh` binary or touches a real repo:
subprocess.run is monkeypatched with a recorder that returns scripted
responses, so the suite asserts the exact argvs cairn WOULD run.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import board, synccmd

CLI = Path(__file__).resolve().parent.parent / "bin" / "cairn"


class GhRecorder:
    """subprocess.run stand-in: records argvs, replays scripted stdouts."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [])

    def __call__(self, argv, **kwargs):
        assert isinstance(argv, list) and argv[0] == "gh"  # list-form only
        assert kwargs.get("shell") is not True
        self.calls.append(argv)
        out = self.responses.pop(0) if self.responses else ""
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")


def _mk_cairn(tmp_path):
    d = tmp_path / ".cairn"
    (d / "tickets").mkdir(parents=True)
    return d


def _add(d, tid, spec=None, **fields):
    board.add_entry(d, {"id": tid, **fields})
    if spec:
        (Path(d) / "tickets" / f"{tid}.md").write_text(spec)


# --- push planning (pure local — must not need gh at all) --------------------

def test_push_plans_create_for_unmapped_tickets(tmp_path, monkeypatch):
    d = _mk_cairn(tmp_path)
    _add(d, "T01", spec="# Build auth\n\nDo the auth thing.\n")
    _add(d, "T02")  # no spec file

    def _boom(*a, **k):  # planning must never shell out
        raise AssertionError("plan_push must not invoke subprocess")
    monkeypatch.setattr(synccmd.subprocess, "run", _boom)

    plans = synccmd.plan_push(d)
    assert [p["op"] for p in plans] == ["create-issue", "create-issue"]
    p1 = plans[0]
    assert p1["tid"] == "T01"
    assert p1["title"] == "[T01] Build auth"
    assert p1["labels"] == ["cairn"]
    assert "Do the auth thing." in p1["body"]          # ticket spec md
    assert '"status": "todo"' in p1["body"]            # board fields
    assert plans[1]["title"] == "[T02] T02"            # spec-less fallback


def test_push_plans_close_when_mapped_ticket_merged(tmp_path):
    d = _mk_cairn(tmp_path)
    _add(d, "T01", spec="# Build auth\n")
    _add(d, "T02", spec="# Ship it\n")
    synccmd.write_mapping(d, {"T01": 7, "T02": 9})
    board.set_fields(d, "T01", {"status": "merged"})

    plans = synccmd.plan_push(d)
    assert plans == [{
        "op": "close-issue", "tid": "T01", "repo": None,
        "issue": 7, "reason": "board status is merged",
    }]  # T02 is mapped and live -> no plan at all


def test_push_plans_close_on_cancelled(tmp_path):
    d = _mk_cairn(tmp_path)
    _add(d, "T01")
    synccmd.write_mapping(d, {"T01": 3})
    board.set_fields(d, "T01", {"status": "cancelled"})
    plans = synccmd.plan_push(d)
    assert plans[0]["op"] == "close-issue" and plans[0]["issue"] == 3


# --- mapping persistence ------------------------------------------------------

def test_mapping_round_trip(tmp_path):
    d = _mk_cairn(tmp_path)
    assert synccmd.read_mapping(d) == {}            # missing file -> empty
    synccmd.write_mapping(d, {"T01": 7, "T02": 12})
    assert (d / "sync.json").exists()
    assert synccmd.read_mapping(d) == {"T01": 7, "T02": 12}
    on_disk = json.loads((d / "sync.json").read_text())
    assert on_disk == {"T01": 7, "T02": 12}


# --- pull planning -------------------------------------------------------------

def test_pull_flags_closed_issue_when_board_not_done(tmp_path, monkeypatch):
    d = _mk_cairn(tmp_path)
    _add(d, "T01")                                   # status todo
    _add(d, "T02")
    board.set_fields(d, "T02", {"status": "merged"})
    synccmd.write_mapping(d, {"T01": 5, "T02": 6})
    rec = GhRecorder(responses=[json.dumps([
        {"number": 5, "title": "[T01] Build auth", "state": "CLOSED"},
        {"number": 6, "title": "[T02] Ship it", "state": "CLOSED"},
    ])])
    monkeypatch.setattr(synccmd.subprocess, "run", rec)

    plans = synccmd.plan_pull(d)
    # exactly one flag: T01 (closed upstream, board still todo); T02 is merged
    assert [p["op"] for p in plans] == ["flag"]
    assert plans[0]["tid"] == "T01" and plans[0]["issue"] == 5
    assert "cairn reconcile" in plans[0]["note"]     # never auto-set merged
    assert board.get_entry(d, "T01")["status"] == "todo"  # board untouched
    # the only gh call was the read-only issue list, labeled cairn
    assert len(rec.calls) == 1
    assert rec.calls[0][:4] == ["gh", "issue", "list", "--label"]
    assert "cairn" in rec.calls[0]


def test_pull_suggests_board_add_for_new_issue(tmp_path, monkeypatch):
    d = _mk_cairn(tmp_path)
    _add(d, "T01")
    rec = GhRecorder(responses=[json.dumps([
        {"number": 12, "title": "Fix flaky CI", "state": "OPEN"},
    ])])
    monkeypatch.setattr(synccmd.subprocess, "run", rec)

    plans = synccmd.plan_pull(d, repo="octo/cairn")
    assert [p["op"] for p in plans] == ["suggest-board-add"]
    assert plans[0]["issue"] == 12
    assert plans[0]["command"] == 'cairn board add \'{"id": "T-gh-12"}\''
    assert ["--repo", "octo/cairn"] == rec.calls[0][-2:]


# --- repo arg validation --------------------------------------------------------

@pytest.mark.parametrize("evil", ["evil;rm", "evil rm/x", "-flag/repo",
                                  "o/r;touch /tmp/pwn", "owner/repo/extra"])
def test_repo_validation_rejects_injection(tmp_path, monkeypatch, evil):
    d = _mk_cairn(tmp_path)
    _add(d, "T01")
    monkeypatch.setattr(synccmd.subprocess, "run", GhRecorder())
    with pytest.raises(ValueError):
        synccmd.plan_push(d, repo=evil)
    with pytest.raises(ValueError):
        synccmd.plan_pull(d, repo=evil)
    with pytest.raises(ValueError):
        synccmd.apply(d, [{"op": "close-issue", "tid": "T01",
                           "issue": 1, "repo": evil}])


def test_repo_validation_accepts_owner_name(tmp_path, monkeypatch):
    d = _mk_cairn(tmp_path)
    monkeypatch.setattr(synccmd.subprocess, "run",
                        GhRecorder(responses=["[]"]))
    assert synccmd.plan_pull(d, repo="octo-org/cairn.test_repo") == []


# --- gh absent --------------------------------------------------------------------

def test_gh_absent_yields_clear_error(tmp_path, monkeypatch):
    d = _mk_cairn(tmp_path)

    def _missing(argv, **kw):
        raise FileNotFoundError("gh")
    monkeypatch.setattr(synccmd.subprocess, "run", _missing)

    with pytest.raises(RuntimeError, match="gh CLI required for sync"):
        synccmd.plan_pull(d)


# --- apply: executes exactly the planned argvs --------------------------------------

def test_apply_executes_planned_gh_argvs_and_persists_mapping(tmp_path, monkeypatch):
    d = _mk_cairn(tmp_path)
    _add(d, "T01", spec="# Build auth\n\nDetails.\n")
    _add(d, "T02")
    board.set_fields(d, "T02", {"status": "merged"})
    synccmd.write_mapping(d, {"T02": 9})

    plans = synccmd.plan_push(d, repo="octo/cairn")
    assert [p["op"] for p in plans] == ["create-issue", "close-issue"]

    rec = GhRecorder(responses=["https://github.com/octo/cairn/issues/41\n", ""])
    monkeypatch.setattr(synccmd.subprocess, "run", rec)
    results = synccmd.apply(d, plans)

    body = plans[0]["body"]
    assert rec.calls == [
        ["gh", "issue", "create", "--title", "[T01] Build auth",
         "--label", "cairn", "--body", body, "--repo", "octo/cairn"],
        ["gh", "issue", "close", "9",
         "--comment", "Closed by cairn sync: board status is merged",
         "--repo", "octo/cairn"],
    ]
    assert results == [
        {"op": "create-issue", "tid": "T01", "issue": 41, "status": "created"},
        {"op": "close-issue", "tid": "T02", "issue": 9, "status": "closed"},
    ]
    # mapping round-trip: the created issue number is persisted in sync.json
    assert synccmd.read_mapping(d) == {"T01": 41, "T02": 9}
    # idempotence: a re-plan now has nothing to create, only T02's close
    replans = synccmd.plan_push(d, repo="octo/cairn")
    assert [p["op"] for p in replans] == ["close-issue"]


def test_apply_skips_informational_plans(tmp_path, monkeypatch):
    d = _mk_cairn(tmp_path)
    rec = GhRecorder()
    monkeypatch.setattr(synccmd.subprocess, "run", rec)
    results = synccmd.apply(d, [
        {"op": "flag", "tid": "T01", "issue": 5, "note": "n"},
        {"op": "suggest-board-add", "issue": 12, "command": "c"},
    ])
    assert rec.calls == []                            # nothing executed
    assert all(r["status"].startswith("skipped") for r in results)


# --- CLI surface (plan path only; push planning needs no gh) -------------------------

def _run_cli(args, cwd):
    return subprocess.run([sys.executable, str(CLI), *args],
                          cwd=cwd, capture_output=True, text=True)


def test_cli_sync_push_prints_json_plan(tmp_path):
    r = _run_cli(["init", "--greenfield"], tmp_path)
    assert r.returncode == 0, r.stderr
    r = _run_cli(["board", "add", '{"id": "T01"}'], tmp_path)
    assert r.returncode == 0, r.stderr

    r = _run_cli(["sync", "push"], tmp_path)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["mode"] == "plan"                      # report-first default
    assert out["plans"][0]["op"] == "create-issue"
    assert out["plans"][0]["title"] == "[T01] T01"


def test_cli_sync_rejects_evil_repo(tmp_path):
    _run_cli(["init", "--greenfield"], tmp_path)
    r = _run_cli(["sync", "push", "--repo", "evil;rm"], tmp_path)
    assert r.returncode != 0
    assert "error" in (r.stderr + r.stdout).lower()
    assert "Traceback" not in r.stderr
