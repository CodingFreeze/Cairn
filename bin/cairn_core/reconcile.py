"""Deterministic git-state classification for the reconciler.

Pure stdlib: shells out to system `git`. No board mutation happens here — this
module answers factual questions about the repo so the orchestrator (cairn-run /
cairn-resume) can decide what to do. Functions return plain values / dicts.
"""
import subprocess


def _git(repo, *args):
    """Run a git command in `repo`; return CompletedProcess (never raises on non-zero)."""
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )


def _check_ref(name, value):
    """Reject a ref/branch/base that could be parsed as a git option.

    A value starting with '-' (e.g. '-x', '--upload-pack=evil') would otherwise be
    consumed by git as a flag. Raise before any git command runs.
    """
    if isinstance(value, str) and value.startswith("-"):
        raise ValueError(f"invalid {name} (must not start with '-'): {value!r}")
    return value


def branch_exists(repo, branch):
    """True if `branch` is a local ref in `repo`."""
    _check_ref("branch", branch)
    r = _git(repo, "rev-parse", "--verify", "--quiet", "--end-of-options", f"refs/heads/{branch}")
    return r.returncode == 0


def branch_has_commits_ahead(repo, branch, base):
    """True if `branch` has at least one commit not reachable from `base`.

    Self-defending: validates BOTH refs before any git command runs, so a
    dashed value can never reach the rev-list range spec regardless of
    caller discipline.
    """
    _check_ref("base", base)
    if not branch_exists(repo, branch):
        return False
    r = _git(repo, "rev-list", "--count", "--end-of-options", f"{base}..{branch}")
    if r.returncode != 0:
        return False
    return int(r.stdout.strip() or "0") > 0


def is_merged(repo, branch, base):
    """True if every commit on `branch` is already reachable from `base`.

    A non-existent branch is treated as not merged (caller distinguishes).
    A branch that exists but is identical to base (0 commits ahead) counts as
    merged — there is nothing left to integrate.
    """
    _check_ref("base", base)
    if not branch_exists(repo, branch):
        return False
    r = _git(repo, "rev-list", "--count", "--end-of-options", f"{base}..{branch}")
    if r.returncode != 0:
        return False
    return int(r.stdout.strip() or "0") == 0


_ACTIVE = {"dispatched", "in-progress"}


def would_rebase_conflict(repo, branch, base):
    """True if rebasing `branch` onto `base` would conflict.

    Non-destructive: uses `git merge-tree` (3-way) which writes nothing to the
    worktree or index. Returns False if the branch is absent or has no commits.
    """
    _check_ref("base", base)
    _check_ref("branch", branch)
    if not branch_has_commits_ahead(repo, branch, base):
        return False
    r = _git(repo, "merge-tree", "--write-tree", "--end-of-options", base, branch)
    # Non-zero exit OR conflict markers in output => conflict.
    if r.returncode != 0:
        return True
    return "<<<<<<<" in r.stdout


def classify_ticket_state(repo, ticket_id, board_entry, base="main"):
    """Reconcile board desired-state vs git actual-state into one classification.

    Returns one of: needs_dispatch, in_progress_resumable, needs_review,
    merged, conflict.

    Logic (no-ff merge policy — orchestrator merges with --no-ff):
      - Board status "merged" always wins immediately.
      - If the branch does not exist → needs_dispatch.
      - tip_in_base:   branch tip is an ancestor of base (git merge-base --is-ancestor).
      - base_advanced: base has commits the branch lacks (base..branch count > 0).
      - ahead:         branch has commits base lacks (base..branch count > 0).

      Because the orchestrator uses --no-ff, a merged branch satisfies BOTH
      tip_in_base AND base_advanced.  A freshly created empty branch at base tip
      satisfies tip_in_base but NOT base_advanced — so the two cases are
      unambiguous (the FF-ambiguity is resolved by policy).

      Decision tree:
        tip_in_base AND base_advanced → merged          (no-ff merged)
        base_sha set AND tip_in_base AND tip != base_sha → merged  (fast-forward)
        ahead AND would conflict      → conflict
        ahead                         → needs_review
        otherwise                     → in_progress_resumable  (branch exists,
                                        no commits ahead, not merged → empty /
                                        just-dispatched; resume it)

      The "needs_dispatch" return only fires when the branch is absent.

      Fast-forward robustness: when the entry carries a `base_sha` (the base tip
      recorded at dispatch), a branch whose tip is now in base and has moved past
      that SHA is treated as merged — this catches FF merges that leave no merge
      commit. Squash merges leave no shared history, so they remain covered by the
      authoritative board status=merged path written by the orchestrator.
    """
    status = board_entry.get("status", "todo")
    branch = board_entry.get("branch") or f"cairn/{ticket_id}"
    _check_ref("base", base)
    _check_ref("branch", branch)

    if status == "merged":
        return "merged"

    if not branch_exists(repo, branch):
        return "needs_dispatch"

    tip_in_base = _branch_tip_in_base(repo, branch, base)
    base_advanced = _base_has_advanced(repo, branch, base)
    ahead = branch_has_commits_ahead(repo, branch, base)
    base_sha = board_entry.get("base_sha")
    tip = _branch_tip(repo, branch)

    # (1) EMPTY / untouched branch guard — MUST win before any merged check.
    # If the branch tip is still EXACTLY the recorded dispatch base_sha, the agent
    # produced no work yet. If base later advances (other tickets merged), the
    # empty tip becomes an ancestor of base (tip_in_base) AND base moves past it
    # (base_advanced) — which would otherwise trip the no-ff merged check below and
    # wrongly mark genuinely-unfinished work 'merged', so cairn-resume would SKIP
    # it. Resume it regardless of whether base advanced.
    if base_sha and tip == base_sha:
        return "in_progress_resumable"

    # (2) merged signals.
    if tip_in_base and base_advanced:
        # No-ff merged: branch tip is reachable from base AND base has moved
        # past the branch (the merge commit is on base, not on the branch).
        # SAFETY (ambiguous legacy case): when base_sha is ABSENT we cannot tell an
        # untouched empty branch (tip==base) apart from a no-ff merge. If the branch
        # has ZERO commits ahead there is no positive merge evidence, so bias to
        # safety and DON'T classify as merged here — fall through to resumable
        # below. Re-dispatching wasted work is safe; skipping unfinished work is not.
        # (Truly-merged tickets are still covered by the status==merged path.)
        if base_sha or ahead:
            return "merged"

    # Fast-forward merge detection via the recorded dispatch base SHA.
    # If the branch tip is now in base AND the branch has advanced past the SHA it
    # was dispatched at, the branch did real work that got folded into base by a
    # fast-forward merge (no merge commit, so base_advanced is False). The empty
    # branch sitting at base_sha (tip == base_sha) was already handled in (1).
    # (Squash merges remain covered by the authoritative board status=merged path
    # written by the orchestrator.)
    if base_sha and tip_in_base and tip != base_sha:
        return "merged"

    # (3) unmerged work on the branch.
    if ahead:
        # Branch has un-merged commits: ready for review unless it would conflict.
        if would_rebase_conflict(repo, branch, base):
            return "conflict"
        return "needs_review"

    # (4) Branch exists, no commits ahead, not merged, and (base_sha absent or
    # tip == base) → empty / just-dispatched. Resume it.
    return "in_progress_resumable"


def _branch_tip(repo, branch):
    """Return the full commit SHA at the tip of `branch` (or '' if unknown)."""
    r = _git(repo, "rev-parse", "--verify", "--end-of-options", f"refs/heads/{branch}")
    return r.stdout.strip() if r.returncode == 0 else ""


def _branch_tip_in_base(repo, branch, base):
    """True if the branch tip commit is reachable from `base` (i.e. merged in)."""
    if not branch_exists(repo, branch):
        return False
    _check_ref("base", base)
    _check_ref("branch", branch)
    r = _git(repo, "merge-base", "--is-ancestor", "--end-of-options", branch, base)
    return r.returncode == 0


def _base_has_advanced(repo, branch, base):
    """True if `base` has commits not reachable from `branch` (base moved past branch)."""
    _check_ref("base", base)
    _check_ref("branch", branch)
    r = _git(repo, "rev-list", "--count", "--end-of-options", f"{branch}..{base}")
    if r.returncode != 0:
        return False
    return int(r.stdout.strip() or "0") > 0


def reconcile_board(repo, board_entries, base="main"):
    """Return a list of {id, status, branch, state} reconciling each ticket.

    `status` is the board's desired status; `state` is the computed actual state
    from classify_ticket_state. This is the data `cairn reconcile` prints as JSON
    and `cairn-resume` walks to decide the next action per ticket.
    """
    _check_ref("base", base)
    out = []
    for e in sorted(board_entries, key=lambda x: x["id"]):
        out.append({
            "id": e["id"],
            "status": e.get("status", "todo"),
            "branch": e.get("branch") or f"cairn/{e['id']}",
            "state": classify_ticket_state(repo, e["id"], e, base=base),
        })
    return out
