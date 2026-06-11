"""Deterministic reconciler-loop steps for /cairn-run.

The orchestration loop used to live as prose in cairn-run.md — every step
(pick ticket, validate, worktree, record base_sha, update board) was re-derived
by the LLM each turn, so the "MANDATORY" rules were only as strong as context
fidelity. This module makes each loop iteration ONE testable CLI call:

    cairn run-lock acquire          -> {"token": ...}   (refuses a second live run)
    cairn step --base B --token T   -> dispatch-context JSON or terminal report
    cairn merge <TID> --base B      -> (mergeflow.py — already extracted)
    cairn run-lock release --token T

`step` is the single writer for the todo->dispatched transition: it resolves
next_ready, creates/reuses the worktree, records base_sha, flips the board, and
emits everything the implementer dispatch needs as JSON. The markdown skill
shrinks to "call step, dispatch the JSON, merge, repeat".
"""
import json
import os
import secrets
import subprocess
import time
from pathlib import Path

from cairn_core import board, boardcheck, resolve
from cairn_core.safepath import atomic_write, safe_open_read, safe_unlink

RUN_LOCK = "run.lock"
# A run lock older than this is presumed dead (crashed session) and may be
# stolen with --steal. Matches the status.py staleness horizon.
LOCK_STALE_SECONDS = 2 * 60 * 60


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo),
                          capture_output=True, text=True)


def _lock_path(cairn_dir):
    return Path(cairn_dir) / RUN_LOCK


def _read_lock(cairn_dir):
    p = _lock_path(cairn_dir)
    if not os.path.lexists(str(p)):
        return None
    with safe_open_read(cairn_dir, p) as fh:
        try:
            return json.loads(fh.read())
        except ValueError:
            return {"token": "", "ts": 0}  # corrupt lock = stealable


def acquire_lock(cairn_dir, steal=False):
    """Acquire the single-run lock. Returns {"token": ...}.

    Refuses (ValueError) if another run holds a fresh lock — this closes the
    two-sessions-both-dispatch-the-same-ticket race (flock in board.py covers
    the board write, but not the read-then-dispatch window across processes).
    A lock older than LOCK_STALE_SECONDS, or any lock when steal=True, is
    replaced.

    Creation uses O_CREAT|O_EXCL (atomic exclusive create, O_NOFOLLOW) so two
    near-simultaneous acquires can never both succeed — the loser sees
    FileExistsError and gets the standard refusal. The stale/steal path
    unlinks then retries the exclusive create once; if ANOTHER stealer wins
    that race we fail closed rather than silently sharing.
    """
    token = secrets.token_hex(16)
    payload = (json.dumps({"token": token, "ts": time.time()}) + "\n").encode()
    lock = _lock_path(cairn_dir)

    def _try_create():
        fd = os.open(str(lock),
                     os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o644)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)

    try:
        _try_create()
        return {"token": token}
    except FileExistsError:
        pass
    existing = _read_lock(cairn_dir)
    if existing and not steal:
        age = time.time() - existing.get("ts", 0)
        if age < LOCK_STALE_SECONDS:
            raise ValueError(
                f"another cairn run holds the lock (age {int(age)}s). "
                "Finish/release it, or pass --steal if it crashed."
            )
    # Stale or stolen: replace, but keep the exclusive-create guarantee.
    safe_unlink(cairn_dir, lock)
    try:
        _try_create()
    except FileExistsError:
        raise ValueError("lost the lock-steal race to another run — retry")
    return {"token": token}


def release_lock(cairn_dir, token):
    """Release the run lock; refuses a token mismatch (ValueError)."""
    existing = _read_lock(cairn_dir)
    if existing is None:
        return {"released": False, "reason": "no lock held"}
    if existing.get("token") != token:
        raise ValueError("run-lock token mismatch — not your lock")
    safe_unlink(cairn_dir, _lock_path(cairn_dir))
    return {"released": True}


def _check_token(cairn_dir, token):
    existing = _read_lock(cairn_dir)
    if existing is None:
        raise ValueError("no run lock held — call `cairn run-lock acquire` first")
    if existing.get("token") != token:
        raise ValueError("run-lock token mismatch — another run owns the loop")
    # Heartbeat: refresh ts so a long-running healthy loop is never stolen.
    atomic_write(cairn_dir, _lock_path(cairn_dir),
                 json.dumps({"token": token, "ts": time.time()}) + "\n")


def _ticket_spec(cairn_dir, tid):
    p = Path(cairn_dir) / "tickets" / f"{tid}.md"
    if not os.path.lexists(str(p)):
        return ""
    with safe_open_read(cairn_dir, p) as fh:
        return fh.read()


def _terminal_report(entries):
    """No ticket ready: distinguish all-done from blocked, with diagnosis."""
    live = [e for e in entries
            if e.get("status") not in ("merged", "cancelled")]
    if not live:
        return {"action": "done",
                "summary": "all tickets merged or cancelled"}
    report = {
        "action": "blocked",
        "live": [{"id": e["id"], "status": e["status"],
                  "depends_on": e.get("depends_on", [])} for e in live],
    }
    cycle = resolve.find_cycle(entries)
    if cycle:
        report["cycle"] = cycle
    missing = resolve.missing_deps(entries)
    if missing:
        report["missing_deps"] = missing
    return report


def step(cairn_dir, base="main", token=None):
    """One reconciler iteration. Returns a dict (the CLI prints it as JSON).

    action=dispatch: ticket flipped to dispatched, worktree ready — the payload
    carries everything the implementer dispatch prompt needs.
    action=done/blocked: terminal — nothing ready (see _terminal_report).
    """
    cairn_dir = Path(cairn_dir)
    repo = cairn_dir.parent
    if token is not None:
        _check_token(cairn_dir, token)
    if base.startswith("-"):
        raise ValueError(f"invalid base (must not start with '-'): {base!r}")
    if _git(repo, "show-ref", "--verify", "--quiet",
            f"refs/heads/{base}").returncode != 0:
        raise ValueError(
            f"base is not an existing local branch: {base} "
            "(unborn HEAD? make an initial commit first)"
        )

    entries = board.read_board(cairn_dir)
    tid = resolve.next_ready(entries)
    if tid is None:
        return _terminal_report(entries)

    entry = board.get_entry(cairn_dir, tid)
    branch = entry.get("branch") or f"cairn/{tid}"
    boardcheck.validate_branch(branch)
    wt = cairn_dir / "worktrees" / tid

    base_sha = _git(repo, "rev-parse", "--verify",
                    "--end-of-options", base).stdout.strip()
    if not base_sha:
        raise ValueError(f"could not resolve base sha for {base!r}")

    branch_exists = _git(repo, "show-ref", "--verify", "--quiet",
                         f"refs/heads/{branch}").returncode == 0
    wt_created_here = False
    if wt.is_dir():
        # Reuse only a healthy worktree already on the ticket branch.
        on = _git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if on != branch:
            raise ValueError(
                f"worktree {wt} exists but is on {on!r}, expected {branch!r} — "
                f"prune it (git worktree remove {wt}) and re-run"
            )
    elif branch_exists:
        r = _git(repo, "worktree", "add", "--end-of-options", str(wt), branch)
        if r.returncode != 0:
            raise ValueError(f"worktree add failed: {r.stderr.strip()}")
        wt_created_here = True
    else:
        r = _git(repo, "worktree", "add", "-b", branch,
                 "--end-of-options", str(wt), base)
        if r.returncode != 0:
            raise ValueError(f"worktree add -b failed: {r.stderr.strip()}")
        wt_created_here = True

    try:
        board.set_fields(cairn_dir, tid, {
            "status": "dispatched", "branch": branch, "base_sha": base_sha,
        })
    except Exception:
        # Don't strand a half-dispatch: if the board flip fails after we just
        # created the worktree, remove it so board and filesystem stay in sync.
        if wt_created_here:
            _git(repo, "worktree", "remove", "--force", str(wt))
        raise
    return {
        "action": "dispatch",
        "id": tid,
        "branch": branch,
        "worktree": str(wt),
        "base": base,
        "base_sha": base_sha,
        "files_owned": entry.get("files_owned", []),
        "depends_on": entry.get("depends_on", []),
        "spec": _ticket_spec(cairn_dir, tid),
    }
