"""Deterministic fake session executor for --mock runs.

Purpose: make the HARNESS testable offline/CI without API spend. It scripts
file edits, ledger updates and git commits exactly like a real session would
produce them, then returns a session record in the same shape runner.py builds
from real `claude -p` output.

HONESTY NOTE: the mock encodes the failure modes we expect the control
condition to exhibit (drift, stale ledger, re-explanation cost, re-planning)
so the pipeline's ability to DETECT them is testable. Mock numbers are
synthetic by construction and are never evidence for or against the thesis —
results JSONs carry "mode": "mock" and RESULTS.md stays pending until a real
run.
"""
import json
import subprocess
from pathlib import Path

# Synthetic token model (deterministic; seed adds a small jitter so the
# aggregation path across seeds is exercised, not to simulate variance).
_BASE_INPUT = 400          # tokens of the bare task instruction
_CAIRN_CONTEXT = 150       # compact board+vault summary read on resume
_CONTROL_CONTEXT = 1100    # prose CLAUDE.md re-read + re-explanation on resume
_OUTPUT_PER_TICKET = 220


def _git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=cairn-eval-bot",
         "-c", "user.email=cairn-eval-bot@example.invalid", *args],
        cwd=repo, check=True, capture_output=True, text=True,
    )


def _write(repo, rel, content):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _complete_ticket(repo, ticket):
    """Scripted implementation of one ticket: write its owned files + commit."""
    for rel in ticket.get("files_owned", []):
        _write(repo, rel, f'"""{ticket["title"]} ({ticket["id"]})."""\n'
                          f"IMPLEMENTED = True\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f'feat({ticket["id"]}): {ticket["title"]}')


def _update_ledger(repo, condition, tickets_by_id, done_ids):
    """Rewrite the memory-layer ledger to reflect done_ids."""
    lines = []
    for tid, t in tickets_by_id.items():
        status = "merged" if tid in done_ids else "todo"
        lines.append({"id": tid, "status": status, "title": t["title"]})
    if condition == "cairn":
        body = "\n".join(json.dumps(e) for e in lines) + "\n"
        _write(repo, ".cairn/board.jsonl", body)
    else:
        rows = "\n".join(f'- {e["id"]} [{e["status"]}] {e["title"]}' for e in lines)
        notes = Path(repo) / "CLAUDE.md"
        head = notes.read_text().split("## Ticket status")[0] if notes.exists() else ""
        _write(repo, "CLAUDE.md", head + "## Ticket status\n" + rows + "\n")


def _write_handoff(repo, condition, tickets_by_id, done_ids):
    remaining = [tid for tid in tickets_by_id if tid not in done_ids]
    pack = ("# Handoff pack\n\n## Done\n"
            + "".join(f"- {t}\n" for t in sorted(done_ids))
            + "\n## Remaining (in order)\n"
            + "".join(f"- {t}: {tickets_by_id[t]['title']}\n" for t in remaining))
    rel = ".cairn/handoff.md" if condition == "cairn" else "HANDOFF.md"
    _write(repo, rel, pack)
    return rel


def run_session(repo, scenario, spec, condition, seed, done_ids):
    """Execute one scripted session. Mutates repo + done_ids; returns a record.

    Control-condition resume sessions deterministically exhibit the documented
    failure modes; cairn-condition sessions resume cleanly. Distractor sessions
    do the distractor task in both conditions.
    """
    tickets_by_id = {t["id"]: t for t in scenario["tickets"]}
    edited, replanned = [], False
    kind = spec["kind"]
    assigned = list(spec.get("complete_through", []))

    if kind == "distractor":
        d = scenario["distractor"]
        for rel, content in d["files"].items():
            _write(repo, rel, content)
            edited.append(rel)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", d["commit_subject"])
    else:
        degraded = condition == "control" and kind == "resume"
        if degraded:
            # Drift: re-edits a file owned by an already-completed ticket
            # (context lost — it does not trust/see the prior session's work).
            prior = sorted(done_ids)
            if prior:
                victim = tickets_by_id[prior[0]]["files_owned"][0]
                _write(repo, victim, "# re-implemented from scratch (drift)\n")
                edited.append(victim)
            # And it re-plans the remaining work instead of resuming.
            replanned = bool(scenario.get("checks", {}).get("forbid_replanning"))
            # Recall-precision failure: touches the distractor's file too.
            if scenario.get("distractor"):
                dfile = sorted(scenario["distractor"]["files"])[0]
                _write(repo, dfile, "# mistakenly extended distractor output\n")
                edited.append(dfile)
            if edited:
                # Commit drift artifacts NOW so they don't get swept into the
                # next ticket's feat() commit (keeps git history attributable).
                _git(repo, "add", "-A")
                _git(repo, "commit", "-m", "chore: stray cleanup (drift artifacts)")
        for tid in assigned:
            _complete_ticket(repo, tickets_by_id[tid])
            edited.extend(tickets_by_id[tid].get("files_owned", []))
            done_ids.add(tid)
        ledger_done = set(done_ids)
        if degraded and assigned:
            # Stale ledger: forgets to record the last ticket it finished.
            ledger_done.discard(assigned[-1])
        _update_ledger(repo, condition, tickets_by_id, ledger_done)
        if spec.get("emit_handoff"):
            edited.append(_write_handoff(repo, condition, tickets_by_id, done_ids))
            _git(repo, "add", "-A")
            _git(repo, "commit", "-m", "docs: write handoff pack")

    context = 0
    if kind == "resume":
        context = _CAIRN_CONTEXT if condition == "cairn" else _CONTROL_CONTEXT
    input_tokens = _BASE_INPUT + context + (seed * 7) % 13
    return {
        "n": spec["n"],
        "kind": kind,
        "condition": condition,
        "mode": "mock",
        "assigned": assigned,
        "edited_files": edited,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": _OUTPUT_PER_TICKET * max(1, len(assigned)),
        },
        "task_prompt_tokens": _BASE_INPUT,
        "replanned": replanned,
    }
