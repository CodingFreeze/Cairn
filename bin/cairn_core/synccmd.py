"""GitHub Issues <-> board sync via the `gh` CLI (report-first).

Sync never silently mutates: plan_push/plan_pull return a diff plan (the
default CLI output), and only --apply executes it. Board fields are locked
down, so the ticket<->issue mapping lives in .cairn/sync.json
({tid: issue_number}), written atomically via safepath.

Security model:
- `gh` is invoked with list-form argv only (never shell=True); titles/bodies
  are single argv elements, so issue text can never be parsed as options/shell.
- A --repo value must match OWNER/NAME charset (REPO_RE) before it reaches gh.
- Pull NEVER auto-sets a board status: git truth beats issue state, so a
  closed-on-GitHub issue only yields a 'flag' plan pointing at `cairn reconcile`.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from cairn_core import board, speccmd
from cairn_core.safepath import atomic_write, safe_open_read

REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SYNC_FILENAME = "sync.json"
LABEL = "cairn"
_DONE = ("merged", "cancelled")
_GH_MISSING = "gh CLI required for sync (https://cli.github.com)"


def _validate_repo(repo):
    """Reject any --repo that is not a plain OWNER/NAME (blocks option/shell text).

    Also refuses a leading '-' (same git-option-injection guard as reconcile's
    _check_ref): '-' is inside the allowed charset but must not start the value.
    """
    if repo is None:
        return None
    if repo.startswith("-") or not REPO_RE.match(repo):
        raise ValueError(f"invalid repo (must be OWNER/NAME): {repo!r}")
    return repo


def _run_gh(args):
    """Run `gh` with list-form argv. Missing binary -> RuntimeError; non-zero -> RuntimeError."""
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError(_GH_MISSING) from None
    if r.returncode != 0:
        raise RuntimeError(f"gh {args[0]} failed: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


# --- mapping store (.cairn/sync.json) ---------------------------------------

def read_mapping(cairn_dir):
    """Return {tid: issue_number} from .cairn/sync.json (missing file -> {})."""
    p = Path(cairn_dir) / SYNC_FILENAME
    if not os.path.lexists(str(p)):
        return {}
    with safe_open_read(cairn_dir, p) as fh:  # symlinked leaf/parent refused
        raw = fh.read()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"{p}: sync mapping must be a JSON object")
    return {str(tid): int(num) for tid, num in data.items()}


def write_mapping(cairn_dir, mapping):
    """Atomically persist the mapping (sorted keys, trailing newline)."""
    p = Path(cairn_dir) / SYNC_FILENAME
    atomic_write(cairn_dir, p, json.dumps(mapping, sort_keys=True, indent=2) + "\n")


# --- plan: push (board -> issues). Pure local read; no gh needed to plan. ----

def _issue_body(entry, spec_md):
    """Issue body = ticket spec markdown + the board entry as a fenced block."""
    fields = json.dumps(entry, indent=2, sort_keys=True)
    spec = spec_md.strip() or "(no ticket spec file)"
    return f"{spec}\n\n---\nCairn board fields:\n```json\n{fields}\n```\n"


def plan_push(cairn_dir, repo=None):
    """Plan board->GitHub: create issues for unmapped tickets, close on done.

    - Ticket without a sync.json mapping -> 'create-issue' (title
      '[<TID>] <ticket spec title>', label 'cairn', body = spec md + fields).
    - Mapped ticket whose status is merged/cancelled -> 'close-issue'.
    Returns a list of plan dicts; nothing is executed here.
    """
    _validate_repo(repo)
    mapping = read_mapping(cairn_dir)
    plans = []
    for e in board.read_board(cairn_dir):
        tid = e["id"]
        if tid not in mapping:
            spec_title, spec_md = speccmd._read_ticket(cairn_dir, tid)
            plans.append({
                "op": "create-issue", "tid": tid, "repo": repo,
                "title": f"[{tid}] {spec_title or tid}",
                "labels": [LABEL],
                "body": _issue_body(e, spec_md),
            })
        elif e.get("status") in _DONE:
            plans.append({
                "op": "close-issue", "tid": tid, "repo": repo,
                "issue": mapping[tid],
                "reason": f"board status is {e['status']}",
            })
    return plans


# --- plan: pull (issues -> board). Read-only gh; never mutates the board. ----

def _list_issues(repo):
    args = ["issue", "list", "--label", LABEL, "--state", "all",
            "--json", "number,title,state", "--limit", "500"]
    if repo:
        args += ["--repo", repo]
    return json.loads(_run_gh(args) or "[]")


_TITLE_TID = re.compile(r"^\[([A-Za-z0-9][A-Za-z0-9._-]*)\]")


def plan_pull(cairn_dir, repo=None):
    """Plan GitHub->board, report-only:

    - Issue closed on GitHub while the board ticket is not merged/cancelled ->
      'flag' (NEVER auto-set merged: git truth beats issue state; the plan
      tells the operator to run `cairn reconcile`).
    - Open cairn-labeled issue with no board ticket -> 'suggest-board-add'
      with a ready-to-run `cairn board add` command.
    """
    _validate_repo(repo)
    entries = {e["id"]: e for e in board.read_board(cairn_dir)}
    rev = {num: tid for tid, num in read_mapping(cairn_dir).items()}
    plans = []
    for issue in _list_issues(repo):
        num, state = issue["number"], issue.get("state", "").upper()
        title = issue.get("title", "")
        tid = rev.get(num)
        if tid is None:  # fall back to the '[TID] ...' title convention
            m = _TITLE_TID.match(title)
            if m and m.group(1) in entries:
                tid = m.group(1)
        if tid is not None and tid in entries:
            if state == "CLOSED" and entries[tid].get("status") not in _DONE:
                plans.append({
                    "op": "flag", "tid": tid, "issue": num, "repo": repo,
                    "note": (f"issue #{num} is closed on GitHub but board status is "
                             f"'{entries[tid].get('status')}' — git truth beats issue "
                             "state; run `cairn reconcile` to verify before updating"),
                })
        elif state == "OPEN":
            new_id = f"T-gh-{num}"
            plans.append({
                "op": "suggest-board-add", "issue": num, "repo": repo,
                "title": title, "tid": new_id,
                "command": "cairn board add "
                           + "'" + json.dumps({"id": new_id}) + "'",
            })
    return plans


# --- apply -------------------------------------------------------------------

def _parse_issue_number(stdout):
    """`gh issue create` prints the issue URL; the number is the last segment."""
    tail = stdout.strip().rstrip("/").rsplit("/", 1)[-1]
    if not tail.isdigit():
        raise RuntimeError(f"could not parse issue number from gh output: {stdout!r}")
    return int(tail)


def apply(cairn_dir, plans):
    """Execute create/close plans via gh; update sync.json. Returns results.

    Every gh arg is re-validated here (repo charset, integer issue number);
    flag/suggest plans are informational and reported as skipped.
    """
    mapping = read_mapping(cairn_dir)
    results = []
    for plan in plans:
        op, repo = plan.get("op"), _validate_repo(plan.get("repo"))
        repo_args = ["--repo", repo] if repo else []
        if op == "create-issue":
            out = _run_gh(["issue", "create", "--title", plan["title"],
                           "--label", ",".join(plan["labels"]),
                           "--body", plan["body"], *repo_args])
            num = _parse_issue_number(out)
            mapping[plan["tid"]] = num
            write_mapping(cairn_dir, mapping)  # persist after each create
            results.append({"op": op, "tid": plan["tid"], "issue": num,
                            "status": "created"})
        elif op == "close-issue":
            num = int(plan["issue"])
            _run_gh(["issue", "close", str(num),
                     "--comment", f"Closed by cairn sync: {plan.get('reason', '')}".strip(),
                     *repo_args])
            results.append({"op": op, "tid": plan["tid"], "issue": num,
                            "status": "closed"})
        else:  # flag / suggest-board-add never mutate anything
            results.append({"op": op, "status": "skipped (informational)"})
    return results


# --- CLI wiring (kept here so bin/cairn stays under its 300-line cap) --------

def register(sub, require_dir):
    """Attach `cairn sync push|pull [--repo R] [--apply]` to the CLI subparsers."""
    ps = sub.add_parser("sync")
    ssub = ps.add_subparsers(dest="direction", required=True)
    for d in ("push", "pull"):
        sp = ssub.add_parser(d)
        sp.add_argument("--repo", default=None)
        sp.add_argument("--apply", action="store_true")
    ps.set_defaults(func=lambda args: run_cli(require_dir(), args))


def run_cli(cairn_dir, args):
    """Report-first: print the JSON plan; with --apply, execute and report both."""
    planner = plan_push if args.direction == "push" else plan_pull
    try:
        plans = planner(cairn_dir, repo=args.repo)
        if not args.apply:
            print(json.dumps({"mode": "plan", "plans": plans}))
            return
        results = apply(cairn_dir, plans)
        print(json.dumps({"mode": "apply", "plans": plans, "results": results}))
    except RuntimeError as exc:
        sys.exit(f"error: {exc}")
