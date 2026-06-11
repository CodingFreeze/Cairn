"""Contracts-as-code tests: add/validate/refuse-overwrite, name charset,
check findings (all four kinds), and strict vs non-strict mergeflow gating.

Mergeflow tests build real throwaway git repos (same pattern as
test_mergeflow_v2.py). tmp_path is realpath-resolved because the macOS /tmp
symlink breaks safepath root checks.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import pytest  # noqa: E402

from cairn_core import board, contracts, mergeflow  # noqa: E402

CLI = Path(__file__).resolve().parent.parent / "bin" / "cairn"
VALID = '{"type": "object", "properties": {"id": {"type": "string"}}}'


@pytest.fixture
def cairn(tmp_path):
    d = Path(os.path.realpath(tmp_path)) / ".cairn"
    d.mkdir()
    return d


# ---------- name charset / contract_path ----------

def test_contract_path_valid_name(cairn):
    p = contracts.contract_path(cairn, "ConfigSchema")
    assert p == cairn / "contracts" / "ConfigSchema.schema.json"


@pytest.mark.parametrize("bad", [
    "", "  ", "a/b", "../x", "a..b", "a>b", "a\nb", "-lead", "a b", None, 7,
])
def test_contract_name_charset_rejected(cairn, bad):
    with pytest.raises((ValueError, TypeError)):
        contracts.contract_path(cairn, bad)


# ---------- add ----------

def test_add_writes_schema_file(cairn):
    p = contracts.add(cairn, "Cfg", VALID)
    assert p.is_file()
    assert json.loads(p.read_text())["type"] == "object"


def test_add_rejects_invalid_json(cairn):
    with pytest.raises(ValueError, match="not valid JSON"):
        contracts.add(cairn, "Cfg", "{nope")
    assert not contracts.contract_path(cairn, "Cfg").exists()


@pytest.mark.parametrize("text", ['{"foo": 1}', "[1, 2]", '"just a string"'])
def test_add_rejects_implausible_schema(cairn, text):
    with pytest.raises(ValueError, match="JSON object with at least one of"):
        contracts.add(cairn, "Cfg", text)


def test_add_refuses_overwrite_without_allow_update(cairn):
    contracts.add(cairn, "Cfg", VALID)
    with pytest.raises(ValueError, match="already exists"):
        contracts.add(cairn, "Cfg", '{"type": "string"}')
    # explicit allow_update redefines deliberately
    contracts.add(cairn, "Cfg", '{"type": "string"}', allow_update=True)
    assert json.loads(contracts.contract_path(cairn, "Cfg").read_text()) == \
        {"type": "string"}


# ---------- check (board-wide findings, one test per kind) ----------

def _kinds(findings):
    return sorted((f["finding"], f["severity"], f["name"]) for f in findings)


def test_check_missing_contract_warn(cairn):
    entries = [{"id": "T01", "produces": ["Cfg"]}]
    assert _kinds(contracts.check(cairn, entries)) == \
        [("missing_contract", "warn", "Cfg")]


def test_check_orphan_consumer_error(cairn):
    entries = [{"id": "T02", "consumes": ["Ghost"]}]
    assert _kinds(contracts.check(cairn, entries)) == \
        [("orphan_consumer", "error", "Ghost")]


def test_check_invalid_contract_error(cairn):
    contracts.add(cairn, "Cfg", VALID)
    contracts.contract_path(cairn, "Cfg").write_text("{broken")
    entries = [{"id": "T01", "produces": ["Cfg"]}]
    assert _kinds(contracts.check(cairn, entries)) == \
        [("invalid_contract", "error", "Cfg")]


def test_check_unused_contract_info(cairn):
    contracts.add(cairn, "Orphaned", VALID)
    assert _kinds(contracts.check(cairn, [])) == \
        [("unused_contract", "info", "Orphaned")]


def test_check_clean_board_no_findings(cairn):
    contracts.add(cairn, "Cfg", VALID)
    entries = [{"id": "T01", "produces": ["Cfg"]},
               {"id": "T02", "consumes": ["Cfg"]}]
    assert contracts.check(cairn, entries) == []


def test_check_ticket_scoped_and_strict_escalation(cairn):
    board.add_entry(cairn, {"id": "T01", "produces": ["Cfg"]})
    board.add_entry(cairn, {"id": "T02", "consumes": ["Cfg", "Ghost"]})
    t2 = board.get_entry(cairn, "T02")
    # scoped to T02: its orphan consume is found; T01's missing Cfg is NOT
    assert _kinds(contracts.check_ticket(cairn, t2)) == \
        [("orphan_consumer", "error", "Ghost")]
    t1 = board.get_entry(cairn, "T01")
    assert _kinds(contracts.check_ticket(cairn, t1)) == \
        [("missing_contract", "warn", "Cfg")]
    # strict escalates missing_contract to error (artifact mandatory pre-merge)
    assert _kinds(contracts.check_ticket(cairn, t1, strict=True)) == \
        [("missing_contract", "error", "Cfg")]


def test_strict_enabled_defensive_config_read(cairn):
    assert contracts.strict_enabled(cairn) is False          # missing
    (cairn / "config.json").write_text("{corrupt")
    assert contracts.strict_enabled(cairn) is False          # corrupt
    (cairn / "config.json").write_text('{"strict_contracts": "yes"}')
    assert contracts.strict_enabled(cairn) is False          # non-bool
    (cairn / "config.json").write_text('{"strict_contracts": true}')
    assert contracts.strict_enabled(cairn) is True


# ---------- mergeflow gate (real git, pattern from test_mergeflow_v2) ----------

def _git(args, cwd):
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)} failed: {r.stderr}"
    return r.stdout.strip()


def _cli(args, cwd, stdin=None):
    return subprocess.run(
        [sys.executable, str(CLI), *args], cwd=str(cwd),
        capture_output=True, text=True, input=stdin,
    )


def _dispatch(tmp_path, tid, produces=None, consumes=None):
    base_sha = _git(["rev-parse", "main"], tmp_path)
    entry = {"id": tid, "status": "dispatched", "branch": f"cairn/{tid}",
             "depends_on": [], "base_sha": base_sha}
    if produces is not None:
        entry["produces"] = produces
    if consumes is not None:
        entry["consumes"] = consumes
    r = _cli(["board", "add", json.dumps(entry)], tmp_path)
    assert r.returncode == 0, r.stderr
    _git(["worktree", "add", "-b", f"cairn/{tid}", f".cairn/worktrees/{tid}", "main"],
         tmp_path)
    (tmp_path / ".cairn" / "worktrees" / tid / "feature.txt").write_text("new\n")


@pytest.fixture
def repo(tmp_path):
    p = Path(os.path.realpath(tmp_path))
    _git(["init"], p)
    _git(["config", "user.email", "t@t.co"], p)
    _git(["config", "user.name", "tester"], p)
    _cli(["init", ".", "--goal", "demo"], p)
    (p / "app.txt").write_text("v1\n")
    _git(["add", "-A"], p)
    _git(["commit", "-m", "baseline"], p)
    return p


def test_merge_nonstrict_warns_in_summary(repo):
    """produces with no contract file: merge proceeds, summary carries the note."""
    _dispatch(repo, "T01", produces=["Cfg"])
    summary = mergeflow.run(repo / ".cairn", "T01")
    assert summary.startswith("OK T01"), summary
    assert "CONTRACTS: 1 finding(s):" in summary
    assert "missing_contract[warn] Cfg" in summary


def test_merge_strict_aborts_pre_mutation(repo):
    """strict_contracts=true: same ticket aborts BEFORE any mutation."""
    (repo / ".cairn" / "config.json").write_text('{"strict_contracts": true}\n')
    _dispatch(repo, "T01", produces=["Cfg"])
    tip = _git(["rev-parse", "main"], repo)

    with pytest.raises(ValueError, match="strict_contracts"):
        mergeflow.run(repo / ".cairn", "T01")

    # nothing mutated: worktree intact, board not merged, base tip unmoved
    assert (repo / ".cairn" / "worktrees" / "T01" / "feature.txt").exists()
    assert board.get_entry(repo / ".cairn", "T01")["status"] == "dispatched"
    assert _git(["rev-parse", "main"], repo) == tip


def test_merge_strict_passes_with_valid_contract(repo):
    (repo / ".cairn" / "config.json").write_text('{"strict_contracts": true}\n')
    contracts.add(repo / ".cairn", "Cfg", VALID)
    _dispatch(repo, "T01", produces=["Cfg"])
    summary = mergeflow.run(repo / ".cairn", "T01")
    assert summary.startswith("OK T01"), summary
    assert "CONTRACTS" not in summary  # zero findings, no note


def test_merge_corrupt_config_is_nonstrict(repo):
    """A corrupt config.json must never block a merge (defensive read)."""
    (repo / ".cairn" / "config.json").write_text("{not json")
    _dispatch(repo, "T01", produces=["Cfg"])
    summary = mergeflow.run(repo / ".cairn", "T01")
    assert summary.startswith("OK T01"), summary
    assert "missing_contract[warn] Cfg" in summary
