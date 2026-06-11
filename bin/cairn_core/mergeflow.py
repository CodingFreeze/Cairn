"""Atomic merge of a ticket worktree into the integration base.

Replaces the by-hand commit -> rebase -> --no-ff merge -> board-set -> worktree-
remove dance that `cairn-run` step 9 documents. Doing it in one deterministic call
removes the half-applied-merge footgun (a shell-quoting slip once left a merge
applied but the board un-updated). Either the ticket fully merges + is recorded +
cleaned up, or we stop BEFORE mutating the board with a clear, actionable message.

The operator-permission gate still lives in `cairn-run`: this helper is only called
AFTER the human approves the merge. It never pushes.
"""
import re
import subprocess
from pathlib import Path

from cairn_core import board, boardcheck, contracts
from cairn_core.safepath import safe_open_read

# Mirror board's ticket-id charset so a crafted id can never be parsed as a git
# option or escape into a path. (A board-known id is already validated; this is a
# cheap defensive recheck before any value flows into git / the filesystem.)
_TID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _git(args, cwd):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True
    )


def _ticket_goal(cairn_dir, tid):
    """First '# ' title line of .cairn/tickets/<tid>.md, or the tid itself.

    (The board has no goal field — the ticket spec markdown is the source of
    truth for the human-readable goal; previously this read entry.get('goal')
    which was always None, so every sweep-commit message was 'feat(T##): T##'.)
    """
    spec = Path(cairn_dir) / "tickets" / f"{tid}.md"
    try:
        with safe_open_read(cairn_dir, spec) as fh:
            for line in fh.read().splitlines():
                if line.startswith("# "):
                    # Single safe line for the commit subject: strip CR (Windows
                    # endings) and anything that isn't one plain line of text.
                    title = line[2:].replace("\r", "").replace("\n", " ").strip()
                    if title:
                        return title
    except (OSError, ValueError):
        pass
    return tid


def run(cairn_dir, tid, base="main"):
    """Atomically merge ticket `tid`'s worktree branch into `base`.

    Returns a one-line summary. Raises ValueError on bad input (dashed base,
    invalid/unknown ticket, missing worktree, failed commit/checkout). On a
    rebase or merge CONFLICT it aborts the operation cleanly and returns a `FAIL`
    summary WITHOUT touching the board, so the operator can resolve by hand.
    """
    if base.startswith("-"):
        raise ValueError(f"invalid base (must not start with '-'): {base!r}")
    if not _TID_RE.match(tid):
        raise ValueError(f"invalid ticket id: {tid!r}")

    cairn_dir = Path(cairn_dir)
    repo = cairn_dir.parent
    # Base must be an existing LOCAL branch — not a tag/SHA/remote/pathspec. A
    # detached or wrong base would merge into the wrong place (or fail late, after
    # the ticket is already rebased). Prove it before any mutation.
    if _git(["show-ref", "--verify", "--quiet", f"refs/heads/{base}"], cwd=repo).returncode != 0:
        raise ValueError(f"base is not an existing local branch: {base}")
    entry = board.get_entry(cairn_dir, tid)
    if entry is None:
        raise ValueError(f"no such ticket: {tid}")
    wt = cairn_dir / "worktrees" / tid
    if not wt.is_dir():
        raise ValueError(f"no worktree for {tid} at {wt}")

    # [P1] Merge EXACTLY the branch the worktree is on — the ref we commit+rebase
    # below. If the board's recorded branch disagrees, the board is stale/wrong;
    # refuse before mutating anything rather than rebase one ref and merge another.
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=wt).stdout.strip()
    if branch == "HEAD":
        # rev-parse --abbrev-ref prints the literal 'HEAD' when detached.
        raise ValueError(
            f"worktree for {tid} is in detached-HEAD state — checkout its ticket "
            f"branch before merging (expected {entry.get('branch') or f'cairn/{tid}'})"
        )
    # Defensive recheck: the live branch name flows into git merge below; hold it
    # to the same charset rules as board-recorded branches.
    boardcheck.validate_branch(branch)
    board_branch = entry.get("branch") or f"cairn/{tid}"
    if branch != board_branch:
        raise ValueError(
            f"worktree branch mismatch for {tid}: worktree on {branch!r} but board "
            f"says {board_branch!r} — refusing to merge a different ref"
        )

    # Contracts gate (data contracts as checkable artifacts). Strictness comes
    # from .cairn/config.json {"strict_contracts": true} — read defensively
    # (missing/corrupt config = non-strict). Strict + any error finding aborts
    # HERE, before any mutation (no commit, no rebase, board untouched);
    # otherwise the findings ride along on the OK/FAIL summary as a warning.
    strict = contracts.strict_enabled(cairn_dir)
    findings = contracts.check_ticket(cairn_dir, entry, strict=strict)
    errors = [f for f in findings if f["severity"] == "error"]
    if strict and errors:
        raise ValueError(
            f"strict_contracts: {len(errors)} contract error(s) for {tid}: "
            + "; ".join(contracts.format_finding(f) for f in errors)
            + " — nothing merged, worktree intact, board unchanged. Fix the "
            "contract(s) (cairn contract add/check) or unset strict_contracts."
        )
    contracts_note = (
        f" CONTRACTS: {len(findings)} finding(s): "
        + "; ".join(contracts.format_finding(f) for f in findings)
        if findings else ""
    )

    # 1. Commit any uncommitted agent changes in the worktree. Surface (don't
    # silently sweep) any dirty path outside the ticket's files_owned scope —
    # fix-forward policy still commits it (work is never dropped on the floor),
    # but the summary names the out-of-scope paths so the operator can audit.
    out_of_scope = []
    # -z = NUL-delimited, never C-quoted — paths with spaces/tabs parse exactly.
    # Record format: "XY <path>\0" (renames: "XY <new>\0<old>\0" — new comes first).
    dirty = _git(["status", "--porcelain", "-z"], cwd=wt).stdout
    if dirty.strip("\0").strip():
        owned = entry.get("files_owned") or []
        if owned:
            recs = dirty.split("\0")
            i = 0
            while i < len(recs):
                rec = recs[i]
                i += 1
                if not rec:
                    continue
                status_xy, p = rec[:2], rec[3:]
                if status_xy and status_xy[0] == "R":
                    i += 1  # skip the rename-source path record
                if p and not any(
                    p == o or p.startswith(o.rstrip("/") + "/") for o in owned
                ):
                    out_of_scope.append(p)
        a = _git(["add", "-A"], cwd=wt)
        if a.returncode != 0:
            raise ValueError(f"git add failed for {tid}: {a.stderr.strip()}")
        c = _git(["commit", "-m", f"feat({tid}): {_ticket_goal(cairn_dir, tid)}"], cwd=wt)
        if c.returncode != 0:
            raise ValueError(f"commit failed for {tid}: {c.stderr.strip()}")

    # 2. Rebase onto base (fix-forward). Conflict => abort, stop, board untouched.
    rb = _git(["rebase", "--end-of-options", base], cwd=wt)
    if rb.returncode != 0:
        _git(["rebase", "--abort"], cwd=wt)
        return (
            f"FAIL {tid}: rebase onto {base} conflicts (fix-forward collision). "
            f"Worktree intact, board unchanged — resolve manually.{contracts_note}"
        )

    # 3. --no-ff merge into base (in the main repo). Conflict => abort, stop.
    co = _git(["checkout", "--end-of-options", base], cwd=repo)
    if co.returncode != 0:
        raise ValueError(f"checkout {base} failed: {co.stderr.strip()}")
    # `-m` must precede `--end-of-options`; everything AFTER --end-of-options is
    # treated as a ref/pathspec, so the branch name (only) goes there.
    mg = _git(
        ["merge", "--no-ff", "-m", f"merge {tid}", "--end-of-options", branch],
        cwd=repo,
    )
    if mg.returncode != 0:
        _git(["merge", "--abort"], cwd=repo)
        return (
            f"FAIL {tid}: --no-ff merge into {base} conflicts. Merge aborted, "
            f"board unchanged. (Rebase passed — investigate.){contracts_note}"
        )

    # 4. Record + 5. clean up — only after a clean merge. The merge is the source
    # of truth, so the board is set first; if worktree removal then fails, say so
    # distinctly (board IS merged, only the leftover worktree needs a manual prune)
    # rather than swallowing it into a misleading "all done".
    board.set_fields(cairn_dir, tid, {"status": "merged"})
    rm = _git(["worktree", "remove", str(wt)], cwd=repo)
    if rm.returncode != 0:
        return (
            f"OK {tid}: --no-ff merged into {base}, board=merged — but worktree "
            f"removal FAILED ({rm.stderr.strip()}); prune it manually: "
            f"git worktree remove {wt}{contracts_note}"
        )
    scope_note = (
        f" WARNING: swept {len(out_of_scope)} path(s) outside files_owned: "
        + ", ".join(sorted(out_of_scope)[:10]) + "."
        if out_of_scope else ""
    )
    return (
        f"OK {tid}: committed + rebased + --no-ff merged into {base}, "
        f"board=merged, worktree removed.{scope_note}{contracts_note}"
    )
