"""Tests for the continuation eval harness (evals/continuation/).

Covers: metrics.py unit behavior, scenario spec validity, and an end-to-end
--mock run producing a results JSON with every metric key. The mock executor
scripts known failure modes into the control condition, so these tests assert
the harness DETECTS them — they say nothing about the thesis itself.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "evals" / "continuation"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, EVAL_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


metrics = _load("metrics")
runner = _load("runner")


# --- metrics unit tests ------------------------------------------------------
def test_parse_board_jsonl():
    text = '{"id": "T01", "status": "merged"}\n\n{"id": "T02", "status": "todo"}\n'
    entries = metrics.parse_board_jsonl(text)
    assert [e["id"] for e in entries] == ["T01", "T02"]


def test_parse_control_ledger_matches_board_shape():
    text = ("# Notes\n\n## Ticket status\n"
            "- T01 [merged] storage layer\n- T02 [todo] model\nnot a ledger line\n")
    entries = metrics.parse_control_ledger(text)
    assert entries == [{"id": "T01", "status": "merged"},
                       {"id": "T02", "status": "todo"}]


def test_commit_ticket_ids_parses_conventional_scope():
    subjects = ["feat(T01): storage", "chore: cleanup", "fix(T02): edge case",
                "docs: handoff", "merge branch"]
    assert metrics.commit_ticket_ids(subjects) == {"T01", "T02"}


def test_integrity_errors_counts_both_directions():
    entries = [{"id": "T01", "status": "merged"},   # merged + committed: ok
               {"id": "T02", "status": "merged"},   # merged, NO commit: 1
               {"id": "T03", "status": "todo"}]     # committed, not merged: 1
    subjects = ["feat(T01): a", "feat(T03): c"]
    assert metrics.integrity_errors(entries, subjects) == 2


def test_tickets_completed_git_is_ground_truth():
    subjects = ["feat(T01): a", "feat(T02): b", "chore: noise"]
    assert metrics.tickets_completed_git(["T01", "T02", "T03"], subjects) == 2


def test_re_explanation_tokens_only_resume_excess():
    records = [
        {"kind": "work", "usage": {"input_tokens": 900}, "task_prompt_tokens": 400},
        {"kind": "resume", "usage": {"input_tokens": 1500}, "task_prompt_tokens": 400},
        {"kind": "resume", "usage": {"input_tokens": 300}, "task_prompt_tokens": 400},
    ]
    # work session ignored; second resume clamps at 0
    assert metrics.re_explanation_tokens(records) == 1100


def test_wrong_file_edits_exempts_memory_and_distractor():
    ownership = {"T01": ["src/a.py"], "T02": ["src/b.py"]}
    records = [
        {"kind": "resume", "assigned": ["T02"],
         "edited_files": ["src/b.py",          # owned by assigned: ok
                          "src/a.py",          # other ticket's file: DRIFT
                          ".cairn/board.jsonl",  # memory: exempt
                          "CLAUDE.md",         # memory: exempt
                          "docs/stray.md"]},   # unowned: DRIFT
        {"kind": "distractor", "assigned": [], "edited_files": ["docs/x.md"]},
    ]
    assert metrics.wrong_file_edits(records, ownership) == 2


def test_replanning_events_resume_only():
    records = [{"kind": "work", "replanned": True},
               {"kind": "resume", "replanned": True},
               {"kind": "resume", "replanned": False}]
    assert metrics.replanning_events(records) == 1


def test_composite_score_perfect_and_floor():
    perfect = {"completion_rate": 1.0, "integrity_errors": 0,
               "wrong_file_edits": 0, "re_explanation_tokens": 0,
               "replanning_events": 0}
    assert metrics.composite_score(perfect) == 100.0
    awful = {"completion_rate": 0.0, "integrity_errors": 9,
             "wrong_file_edits": 9, "re_explanation_tokens": 10 ** 6,
             "replanning_events": 9}
    assert metrics.composite_score(awful) == 0.0


def test_aggregate_means_across_seeds():
    a = {k: 2.0 for k in metrics.METRIC_KEYS}
    b = {k: 4.0 for k in metrics.METRIC_KEYS}
    agg = metrics.aggregate([a, b])
    assert all(agg[k] == 3.0 for k in metrics.METRIC_KEYS)


# --- scenario spec validity ----------------------------------------------------
def _scenarios():
    return [json.loads(p.read_text())
            for p in sorted((EVAL_DIR / "scenarios").glob("*.json"))]


def test_three_scenarios_exist_with_md_companions():
    specs = _scenarios()
    assert {s["id"] for s in specs} == {"s1-resume", "s2-toolswitch", "s3-return"}
    for s in specs:
        assert (EVAL_DIR / "scenarios" / f"{s['id']}.md").exists()


def test_scenario_dags_are_valid():
    for s in _scenarios():
        ids = [t["id"] for t in s["tickets"]]
        assert len(ids) == len(set(ids)), s["id"]
        known = set(ids)
        for t in s["tickets"]:
            assert set(t["depends_on"]) <= known
            assert t["files_owned"], f"{s['id']}/{t['id']} owns no files"
        # acyclic + sessions respect dependency order (Kahn-style sweep)
        done = set()
        for spec in s["sessions"]:
            for tid in spec.get("complete_through", []):
                t = next(x for x in s["tickets"] if x["id"] == tid)
                assert set(t["depends_on"]) <= done, f"{s['id']}: {tid} early"
                done.add(tid)
        assert done == known, f"{s['id']}: sessions don't cover all tickets"


def test_scenario_shapes():
    for s in _scenarios():
        assert s["fixture"]["files"]
        kinds = [x["kind"] for x in s["sessions"]]
        assert "resume" in kinds
        if s["id"] == "s1-resume":
            assert len(s["tickets"]) == 6 and kinds == ["work", "resume"]
            assert s["sessions"][0]["complete_through"] == ["T01", "T02", "T03"]
        if s["id"] == "s2-toolswitch":
            assert s["sessions"][0]["emit_handoff"] is True
            assert s["sessions"][1]["context"] == "handoff-only"
        if s["id"] == "s3-return":
            assert kinds == ["work", "distractor", "resume"]
            assert s["distractor"]["files"] and s["distractor"]["prompt"]


# --- runner --mock end-to-end --------------------------------------------------
def _run_mock(tmp_path, extra=()):
    out = runner.main(["--mock", "--out", str(tmp_path), "--seeds", "1,2", *extra])
    return json.loads(Path(out).read_text())


def test_mock_run_produces_complete_results_json(tmp_path):
    data = _run_mock(tmp_path)
    assert data["mode"] == "mock"
    assert "synthetic" in data["disclaimer"] or "MOCK" in data["disclaimer"]
    assert data["seeds"] == [1, 2]
    assert data["metric_keys"] == metrics.METRIC_KEYS
    assert set(data["scenarios"]) == {"s1-resume", "s2-toolswitch", "s3-return"}
    for cell in data["scenarios"].values():
        assert set(cell) == {"cairn", "control"}
        for cond_data in cell.values():
            assert set(metrics.METRIC_KEYS) <= set(cond_data["aggregate"])
            assert len(cond_data["per_seed"]) == 2
            for run in cond_data["per_seed"]:
                assert set(metrics.METRIC_KEYS) <= set(run["metrics"])
                assert all(r["mode"] == "mock" for r in run["sessions"])


def test_mock_run_is_deterministic_per_seed(tmp_path):
    a = _run_mock(tmp_path / "a", ("--scenario", "s1-resume"))
    b = _run_mock(tmp_path / "b", ("--scenario", "s1-resume"))
    assert (a["scenarios"]["s1-resume"]["cairn"]["aggregate"]
            == b["scenarios"]["s1-resume"]["cairn"]["aggregate"])


def test_mock_detects_scripted_control_failures(tmp_path):
    """The mock injects drift/staleness/replanning into control resumes; the
    pipeline must surface them (and a clean cairn run as clean). This tests
    the harness's detection power, NOT the thesis."""
    data = _run_mock(tmp_path)
    for sid, cell in data["scenarios"].items():
        cairn, control = cell["cairn"]["aggregate"], cell["control"]["aggregate"]
        assert cairn["wrong_file_edits"] == 0, sid
        assert cairn["integrity_errors"] == 0, sid
        assert cairn["replanning_events"] == 0, sid
        assert control["wrong_file_edits"] >= 1, sid
        assert control["integrity_errors"] >= 1, sid
        assert control["re_explanation_tokens"] > cairn["re_explanation_tokens"], sid
    # s3's distractor must cost control an extra wrong-file edit (recall precision)
    assert (data["scenarios"]["s3-return"]["control"]["aggregate"]["wrong_file_edits"]
            > data["scenarios"]["s1-resume"]["control"]["aggregate"]["wrong_file_edits"])


def test_runner_cli_invocation(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(EVAL_DIR / "runner.py"), "--mock",
         "--scenario", "s2-toolswitch", "--condition", "cairn",
         "--seeds", "1", "--out", str(tmp_path)],
        capture_output=True, text=True, check=True)
    assert "results ->" in proc.stdout
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert list(data["scenarios"]) == ["s2-toolswitch"]
    assert list(data["scenarios"]["s2-toolswitch"]) == ["cairn"]


# --- honesty guards ------------------------------------------------------------
def test_results_md_is_marked_pending():
    text = (ROOT / "evals" / "RESULTS.md").read_text()
    assert "No public results yet" in text
    assert "runner.py --mock" in text


def test_readme_documents_methodology_and_threats():
    text = (ROOT / "evals" / "README.md").read_text()
    for needle in ("Threats to validity", "paired", "CLAUDE.md", "seeds",
                   "composite_score", "model nondeterminism".title()):
        assert needle.lower() in text.lower(), needle
