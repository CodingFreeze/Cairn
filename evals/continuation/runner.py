#!/usr/bin/env python3
"""Cairn continuation eval runner.

Orchestrates one benchmark run: for every (scenario x condition x seed) it
sets up a scratch git repo with the scenario fixture, seeds the memory layer
for the condition, executes the scenario's session plan with a hard kill
between sessions (every session is a brand-new process / fresh context), then
computes metrics from the artifacts (ledger, git log, session records) and
writes evals/results/<timestamp>.json.

Modes:
  --mock   deterministic scripted sessions (mock_session.py) — validates the
           harness offline/CI with zero API spend. Mock output is NOT evidence.
  (real)   invokes `claude -p <prompt> --output-format json` per session.
           Override the binary with $CLAUDE_BIN or --claude-bin.

Usage:
  python3 evals/continuation/runner.py --mock
  python3 evals/continuation/runner.py --mock --scenario s1-resume --seeds 1
  CLAUDE_BIN=claude python3 evals/continuation/runner.py --seeds 1,2,3
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import metrics        # noqa: E402
import mock_session   # noqa: E402

SCENARIOS_DIR = HERE / "scenarios"
DEFAULT_OUT = HERE.parent / "results"
CONDITIONS = ("cairn", "control")


def _git(repo, *args):
    return subprocess.run(
        ["git", "-c", "user.name=cairn-eval-bot",
         "-c", "user.email=cairn-eval-bot@example.invalid", *args],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout


def load_scenarios(only=None):
    out = []
    for p in sorted(SCENARIOS_DIR.glob("*.json")):
        s = json.loads(p.read_text())
        if only in (None, "all", s["id"]):
            out.append(s)
    if not out:
        raise SystemExit(f"no scenario matches {only!r} in {SCENARIOS_DIR}")
    return out


def setup_repo(scenario, condition):
    """Create the scratch repo: fixture files + seeded memory layer."""
    repo = tempfile.mkdtemp(prefix=f"cairn-eval-{scenario['id']}-{condition}-")
    _git(repo, "init", "-q")
    for rel, content in scenario["fixture"]["files"].items():
        p = Path(repo) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    tasklist = "".join(
        f'- {t["id"]}: {t["title"]} (deps: {",".join(t["depends_on"]) or "none"}, '
        f'files: {",".join(t["files_owned"])})\n' for t in scenario["tickets"])
    if condition == "cairn":
        cd = Path(repo) / ".cairn"
        (cd / "vault").mkdir(parents=True)
        board = "\n".join(json.dumps({"id": t["id"], "status": "todo",
                                      "title": t["title"],
                                      "depends_on": t["depends_on"],
                                      "files_owned": t["files_owned"]})
                          for t in scenario["tickets"]) + "\n"
        (cd / "board.jsonl").write_text(board)
        (cd / "vault" / "decisions.md").write_text("# Decisions\n\n- Seeded task DAG; complete tickets in dependency order.\n")
        (cd / "vault" / "issues.md").write_text("# Issues\n")
        (cd / "vault" / "map.md").write_text("# Map\n\n" + tasklist)
    else:
        (Path(repo) / "CLAUDE.md").write_text(
            "# Project notes\n\n## Task list\n" + tasklist + "\n"
            "## Ticket status\n"
            + "".join(f'- {t["id"]} [todo] {t["title"]}\n' for t in scenario["tickets"]))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "chore: seed eval fixture")
    return repo


def _build_prompt(scenario, spec, condition):
    tids = ", ".join(spec.get("complete_through", []))
    if spec["kind"] == "distractor":
        return scenario["distractor"]["prompt"]
    if condition == "cairn":
        ctx = ("Resume from memory: read .cairn/board.jsonl and .cairn/vault/ first "
               "(this is your /cairn-resume step), then continue without re-planning.")
        if spec.get("context") == "handoff-only":
            ctx = ("You are a DIFFERENT coding tool taking over. Your ONLY context "
                   "is the handoff pack at .cairn/handoff.md — read it and continue.")
    else:
        ctx = "Read CLAUDE.md for project notes, then do the work."
        if spec.get("context") == "handoff-only":
            ctx = ("You are a DIFFERENT coding tool taking over. Read only HANDOFF.md "
                   "if present, else CLAUDE.md, and continue.")
    return (f"{ctx}\nComplete tickets {tids} for: {scenario['title']}. "
            f"Commit each ticket as 'feat(<id>): <title>' touching only its owned "
            f"files, and update the ticket-status ledger "
            f"({'.cairn/board.jsonl' if condition == 'cairn' else 'CLAUDE.md'}) "
            f"to [merged] when done."
            + (" Then write a portable handoff pack." if spec.get("emit_handoff") else ""))


def _real_session(repo, scenario, spec, condition, claude_bin, model, budget):
    """One real session via `claude -p`. The subprocess exiting IS the hard
    kill: the next session starts a brand-new process with fresh context."""
    prompt = _build_prompt(scenario, spec, condition)
    before = _git(repo, "rev-parse", "HEAD").strip()
    cmd = [claude_bin, "-p", prompt, "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True,
                          timeout=budget)
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        payload = {}
    usage = payload.get("usage", {}) or {}
    after = _git(repo, "rev-parse", "HEAD").strip()
    edited = []
    if after != before:
        edited = [f for f in _git(repo, "diff", "--name-only",
                                  before, after).splitlines() if f]
    result_text = str(payload.get("result", ""))
    return {
        "n": spec["n"], "kind": spec["kind"], "condition": condition,
        "mode": "real", "assigned": list(spec.get("complete_through", [])),
        "edited_files": edited,
        "usage": {"input_tokens": int(usage.get("input_tokens", 0)),
                  "output_tokens": int(usage.get("output_tokens", 0))},
        "task_prompt_tokens": len(prompt) // 4,
        # Heuristic (documented in README): a resume session that emits a fresh
        # plan header re-planned instead of resuming.
        "replanned": spec["kind"] == "resume" and "# Plan" in result_text,
    }


def run_cell(scenario, condition, seed, args):
    """One (scenario, condition, seed) cell -> per-seed metrics dict."""
    repo = setup_repo(scenario, condition)
    records, done_ids = [], set()
    try:
        for spec in scenario["sessions"]:
            if args.mock:
                rec = mock_session.run_session(repo, scenario, spec,
                                               condition, seed, done_ids)
            else:
                rec = _real_session(repo, scenario, spec, condition,
                                    args.claude_bin, args.model,
                                    args.session_timeout)
            records.append(rec)
            # Hard kill boundary: nothing survives between sessions except the
            # repo on disk (and its memory layer). Mock + real both honor this.
        if condition == "cairn":
            ledger = metrics.parse_board_jsonl(
                (Path(repo) / ".cairn" / "board.jsonl").read_text())
        else:
            ledger = metrics.parse_control_ledger(
                (Path(repo) / "CLAUDE.md").read_text())
        subjects = _git(repo, "log", "--format=%s").splitlines()
        m = metrics.compute_all(scenario["tickets"], records, ledger, subjects)
        return {"seed": seed, "metrics": m, "sessions": records}
    finally:
        if not args.keep_repos:
            shutil.rmtree(repo, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mock", action="store_true",
                    help="deterministic offline run (harness validation only)")
    ap.add_argument("--scenario", default="all")
    ap.add_argument("--condition", default="both", choices=("both",) + CONDITIONS)
    ap.add_argument("--seeds", default="1,2,3",
                    help="comma-separated seed list (default 1,2,3)")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--claude-bin", default=os.environ.get("CLAUDE_BIN", "claude"))
    ap.add_argument("--model", default=os.environ.get("CAIRN_EVAL_MODEL"))
    ap.add_argument("--session-timeout", type=int, default=900,
                    help="hard kill: per-session wall-clock budget (seconds)")
    ap.add_argument("--keep-repos", action="store_true")
    args = ap.parse_args(argv)

    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    conditions = CONDITIONS if args.condition == "both" else (args.condition,)
    results = {
        "run_id": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
        "mode": "mock" if args.mock else "real",
        "model": None if args.mock else (args.model or "claude-cli-default"),
        "seeds": seeds,
        "metric_keys": metrics.METRIC_KEYS,
        "disclaimer": ("MOCK RUN — synthetic scripted sessions; validates the "
                       "harness only, not evidence for the thesis.") if args.mock
                      else "real run",
        "scenarios": {},
    }
    for scenario in load_scenarios(args.scenario):
        cell = {}
        for condition in conditions:
            per_seed = [run_cell(scenario, condition, seed, args)
                        for seed in seeds]
            cell[condition] = {
                "per_seed": per_seed,
                "aggregate": metrics.aggregate([r["metrics"] for r in per_seed]),
            }
        results["scenarios"][scenario["id"]] = cell
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{results['run_id']}.json"
    out_path.write_text(json.dumps(results, indent=2) + "\n")
    for sid, cell in results["scenarios"].items():
        for cond, data in cell.items():
            agg = data["aggregate"]
            print(f"{sid:14s} {cond:7s} score={agg['composite_score']:6.2f} "
                  f"done={agg['tickets_completed']:.1f}/{agg['tickets_total']:.0f} "
                  f"integrity_err={agg['integrity_errors']:.1f} "
                  f"drift={agg['wrong_file_edits']:.1f} "
                  f"reexplain_tok={agg['re_explanation_tokens']:.0f}")
    print(f"results -> {out_path}")
    return str(out_path)


if __name__ == "__main__":
    main()
