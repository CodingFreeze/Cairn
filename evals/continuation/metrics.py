"""Pure metric functions for the Cairn continuation eval.

Every function here takes plain data (parsed board entries, git log subjects,
session records) and returns numbers. No I/O, no subprocess — runner.py owns
artifact collection, this module owns the math, so each metric is unit-testable
in isolation.

Session record shape (produced by mock_session.py and runner._real_session):
    {"n": int, "kind": "work"|"resume"|"distractor", "condition": str,
     "assigned": [ticket ids], "edited_files": [paths],
     "usage": {"input_tokens": int, "output_tokens": int},
     "task_prompt_tokens": int, "replanned": bool}
"""
import json
import re

# Canonical metric keys — the contract between runner, results JSON and tests.
METRIC_KEYS = [
    "tickets_total",
    "tickets_completed",
    "completion_rate",
    "integrity_errors",
    "re_explanation_tokens",
    "wrong_file_edits",
    "replanning_events",
    "composite_score",
]

DONE_STATUSES = {"merged"}

# Memory-layer paths are exempt from drift counting: updating the board, the
# vault, CLAUDE.md notes or a handoff pack is bookkeeping, not a task edit.
_MEMORY_PREFIXES = (".cairn/",)
_MEMORY_FILES = {"CLAUDE.md", "HANDOFF.md"}

# Commit subjects carry the ticket id as a conventional-commit scope:
# "feat(T01): storage layer". This is how board state is checked against git.
_COMMIT_TICKET_RE = re.compile(r"^\w+\(([A-Za-z0-9._-]+)\):")

# Control-condition ledger line inside CLAUDE.md: "- T01 [merged] storage layer"
_LEDGER_LINE_RE = re.compile(r"^- ([A-Za-z0-9._-]+)\s+\[([a-z-]+)\]")


# --- parsers ----------------------------------------------------------------
def parse_board_jsonl(text):
    """Parse .cairn/board.jsonl text into a list of entry dicts."""
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def parse_control_ledger(text):
    """Parse the '## Ticket status' ledger in a control-condition CLAUDE.md.

    Returns board-shaped entries [{"id", "status"}] so every downstream metric
    is computed identically for both conditions (symmetric comparison).
    """
    entries = []
    for line in text.splitlines():
        m = _LEDGER_LINE_RE.match(line.strip())
        if m:
            entries.append({"id": m.group(1), "status": m.group(2)})
    return entries


def commit_ticket_ids(git_subjects):
    """Extract ticket ids from conventional-commit subjects."""
    ids = set()
    for subject in git_subjects:
        m = _COMMIT_TICKET_RE.match(subject.strip())
        if m:
            ids.add(m.group(1))
    return ids


# --- metrics ----------------------------------------------------------------
def tickets_completed(entries):
    """Number of ledger entries in a done status (the memory layer's CLAIM)."""
    return sum(1 for e in entries if e.get("status") in DONE_STATUSES)


def tickets_completed_git(ticket_ids, git_subjects):
    """Number of tickets with a matching commit — git is ground truth of work
    actually done; ledger staleness is scored separately by integrity_errors
    (so a stale ledger isn't double-penalized as incomplete work)."""
    return len(set(ticket_ids) & commit_ticket_ids(git_subjects))


def integrity_errors(entries, git_subjects):
    """Board-vs-git integrity errors (both directions).

    1. A ticket marked done on the ledger with NO commit referencing it
       (the memory layer claims work that git cannot corroborate).
    2. A commit referencing a ticket that the ledger does NOT mark done
       (work happened but the memory layer was never updated).
    Each mismatch counts once.
    """
    done = {e["id"] for e in entries if e.get("status") in DONE_STATUSES}
    committed = commit_ticket_ids(git_subjects)
    return len(done - committed) + len(committed - done)


def re_explanation_tokens(session_records):
    """Prompt tokens spent re-establishing context in resume sessions.

    For every session of kind "resume": input tokens consumed beyond the bare
    task instruction (task_prompt_tokens). That excess is exactly the cost of
    reading memory artifacts / re-explaining prior state to a fresh context.
    """
    total = 0
    for r in session_records:
        if r.get("kind") != "resume":
            continue
        excess = r.get("usage", {}).get("input_tokens", 0) - r.get("task_prompt_tokens", 0)
        total += max(0, excess)
    return total


def _is_memory_path(path):
    return path in _MEMORY_FILES or any(path.startswith(p) for p in _MEMORY_PREFIXES)


def wrong_file_edits(session_records, ownership):
    """Count drift: files edited outside the session's assigned tickets.

    ownership maps ticket id -> list of owned file paths. For each work/resume
    session, any edited file that is neither owned by an assigned ticket nor a
    memory-layer file counts as one wrong-file edit. Distractor sessions are
    intentionally off-task and excluded.
    """
    count = 0
    for r in session_records:
        if r.get("kind") not in ("work", "resume"):
            continue
        allowed = set()
        for tid in r.get("assigned", []):
            allowed.update(ownership.get(tid, []))
        for path in r.get("edited_files", []):
            if path not in allowed and not _is_memory_path(path):
                count += 1
    return count


def replanning_events(session_records):
    """Sessions that re-planned instead of resuming (kind=resume only)."""
    return sum(1 for r in session_records
               if r.get("kind") == "resume" and r.get("replanned"))


def composite_score(metrics):
    """Single 0–100 score per the rubric in evals/README.md.

    completion (50) + integrity (20) + drift (15) + efficiency (15),
    minus 5 per re-planning event. Floor 0.
    """
    completion = 50.0 * metrics["completion_rate"]
    integrity = max(0.0, 20.0 - 10.0 * metrics["integrity_errors"])
    drift = max(0.0, 15.0 - 5.0 * metrics["wrong_file_edits"])
    efficiency = 15.0 / (1.0 + metrics["re_explanation_tokens"] / 1000.0)
    penalty = 5.0 * metrics["replanning_events"]
    return round(max(0.0, completion + integrity + drift + efficiency - penalty), 2)


def compute_all(tickets, session_records, ledger_entries, git_subjects):
    """Compute every metric for one (scenario, condition, seed) run."""
    ownership = {t["id"]: list(t.get("files_owned", [])) for t in tickets}
    total = len(tickets)
    done = tickets_completed_git([t["id"] for t in tickets], git_subjects)
    m = {
        "tickets_total": total,
        "tickets_completed": done,
        "completion_rate": round(done / total, 4) if total else 0.0,
        "integrity_errors": integrity_errors(ledger_entries, git_subjects),
        "re_explanation_tokens": re_explanation_tokens(session_records),
        "wrong_file_edits": wrong_file_edits(session_records, ownership),
        "replanning_events": replanning_events(session_records),
    }
    m["composite_score"] = composite_score(m)
    return m


def aggregate(per_seed_metrics):
    """Mean of every metric across seeds (the published number per cell)."""
    if not per_seed_metrics:
        return {k: 0 for k in METRIC_KEYS}
    out = {}
    for key in METRIC_KEYS:
        vals = [m[key] for m in per_seed_metrics]
        out[key] = round(sum(vals) / len(vals), 4)
    return out
