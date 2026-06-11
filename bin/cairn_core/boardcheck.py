"""Validation rules for board.jsonl entries (split from board.py for the
300-line cap; board.py owns storage/locking, this module owns the charset
and type invariants).

SECURITY context: ticket ids become filesystem paths (.cairn/worktrees/<id>)
and git refs (cairn/<id>); branch names are passed to git commands; contract
names are embedded in generated HTML/JS; depends_on ids are emitted into
Mermaid edge syntax. Every rule here exists to keep one of those sinks safe
against a hand-edited or committed board.jsonl.
"""
import re

# Safe ticket-id charset: alphanumeric start, then alphanumerics/._- — no '/', no
# leading '-' (git option), and '..' rejected separately. Prevents path traversal
# when the id is used in .cairn/worktrees/<id> and the cairn/<id> branch ref.
# Use \Z (absolute string end), NOT $ — $ matches BEFORE a trailing newline, so "T01\n"
# would pass and then desync from $(cairn next), which strips the newline. Paired with
# fullmatch below as belt-and-suspenders against any embedded/trailing newline.
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")

# Branch names allow '/' (cairn/T01) but keep every other id rule: alphanumeric
# start (no leading '-' = git option), no '..', no whitespace/control chars.
BRANCH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*\Z")

VALID_STATUS = {
    "todo", "dispatched", "in-progress", "pr-open", "merged", "blocked",
    "cancelled",
}

# Fields callers may mutate via set_fields ("id"/"updated"/"dispatched_at" are
# internal-only). schema/produces/consumes carry the data-contract model the
# spec graph renders: schema=ticket DEFINES a contract ([SCHEMA]);
# produces/consumes=contract names (a schema edge is drawn producer -> consumer
# of a shared contract).
SETTABLE_FIELDS = {
    "status", "branch", "pr", "owner", "depends_on", "files_owned", "base_sha",
    "schema", "produces", "consumes",
}


def validate_ticket_id(ticket_id):
    """Validate a ticket id against the safe charset and no-path-traversal rules.

    Raises ValueError if the id is not a non-empty str, does not match ID_RE,
    or contains '..'. Call this in both add_entry and read_board so a hand-edited
    or legacy board.jsonl cannot introduce an unsafe id into the control plane.
    """
    if not isinstance(ticket_id, str) or not ticket_id.strip():
        raise ValueError("ticket id must be a non-empty string")
    if not ID_RE.fullmatch(ticket_id) or ".." in ticket_id or "\n" in ticket_id:
        raise ValueError(
            "ticket id must match [A-Za-z0-9][A-Za-z0-9._-]* and contain no '..' "
            f"(got: {ticket_id!r})"
        )


def validate_branch(branch):
    """Validate a branch name (str or None) against the safe ref charset.

    Branch values flow into git commands (mergeflow merge/rebase, reconcile
    rev-list). Every git call also uses --end-of-options, but the charset rule
    makes the entries self-defending regardless of sink discipline.
    """
    if branch is None:
        return
    if not isinstance(branch, str):
        raise ValueError(f"branch must be str or None, got: {type(branch).__name__}")
    if not BRANCH_RE.fullmatch(branch) or ".." in branch or "\n" in branch:
        raise ValueError(
            "branch must match [A-Za-z0-9][A-Za-z0-9._/-]* and contain no '..' "
            f"(got: {branch!r})"
        )
    # git check-ref-format extras the charset alone can't express: a component
    # ending in '.lock' collides with git's own ref lock files; a trailing dot
    # and a dot-leading component are git-forbidden. Catch them here so they
    # fail as a clean ValueError instead of an opaque git error downstream.
    if branch.endswith(".lock") or "/." in branch or branch.endswith("."):
        raise ValueError(
            f"branch contains a git-forbidden pattern (.lock suffix, trailing "
            f"dot, or '/.' component): {branch!r}"
        )


def validate_settable(fields):
    """Type-check the subset of `fields` that are settable board fields.

    Rules: status in VALID_STATUS; depends_on/files_owned = list of str;
    branch = safe ref charset or None; owner/base_sha = str or None;
    pr = int or None. Unknown keys are ignored here (set_fields enforces the
    allow-list separately). Raises ValueError on a bad type.
    """
    for k, v in fields.items():
        if k == "status":
            if v not in VALID_STATUS:
                raise ValueError(f"invalid status: {v}")
        elif k == "pr":
            if v is not None and not isinstance(v, int):
                raise ValueError(f"pr must be int or None, got: {type(v).__name__}")
        elif k == "branch":
            validate_branch(v)
        elif k in ("owner", "base_sha"):
            if v is not None and not isinstance(v, str):
                raise ValueError(f"{k} must be str or None, got: {type(v).__name__}")
        elif k == "schema":
            if not isinstance(v, bool):
                raise ValueError(f"schema must be bool, got: {type(v).__name__}")
        elif k in ("depends_on", "files_owned", "produces", "consumes"):
            if not isinstance(v, list):
                raise ValueError(f"{k} must be a list, got: {type(v).__name__}")
            for item in v:
                if not isinstance(item, str):
                    raise ValueError(f"{k} items must be str, got: {type(item).__name__}")
            if k in ("produces", "consumes"):
                # Contract names go into the JSON-escaped HTML drawer and are used
                # as producer-index keys in the graph JS. Reject a newline (markup
                # smuggling past the island) and '>' (the JS edge-key separator —
                # a '>' would silently corrupt the producer lookup and drop edges).
                for c in v:
                    if "\n" in c or ">" in c:
                        raise ValueError(
                            f"{k} name must not contain a newline or '>': {c!r}"
                        )
            if k == "depends_on":
                # Each depends_on item is a TICKET-ID reference that is later
                # emitted into Mermaid edge syntax (dep --> id). Apply the SAME
                # id charset/no-traversal rules so a newline / '-->' / directive
                # cannot break out of the edge context. files_owned are paths, not
                # ids, so they are NOT id-validated.
                for d in v:
                    if not ID_RE.fullmatch(d) or ".." in d or "\n" in d:
                        raise ValueError(f"invalid depends_on id: {d!r}")


def validate_read_entry(path, e):
    """Per-entry validation applied on every board read (fail-closed).

    A hand-edited or committed board.jsonl must not be able to introduce an
    unsafe id, status, branch, or depends_on into the control plane.
    """
    entry_id = e.get("id")
    try:
        validate_ticket_id(entry_id)
    except ValueError:
        raise ValueError(f"{path}: invalid ticket id: {entry_id!r}")
    # Use presence (`in`), NOT .get() — .get conflates an explicit
    # "status": null with a missing key, letting a hand-edited null pass.
    if "status" in e:
        entry_status = e["status"]
        if not isinstance(entry_status, str) or entry_status not in VALID_STATUS:
            raise ValueError(f"{path}: invalid status for {entry_id}: {entry_status!r}")
    if "branch" in e and e["branch"] is not None:
        try:
            validate_branch(e["branch"])
        except ValueError:
            raise ValueError(f"{path}: invalid branch for {entry_id}: {e['branch']!r}")
    # DATA-INTEGRITY: depends_on must be a list when present. Read the raw
    # key (NOT `e.get(...) or []`) so a malformed hand-edited value like
    # null/0/"" is NOT silently coerced to [] — that would drop edges. An
    # absent key still defaults to []; any non-list value fails closed.
    if "depends_on" in e and not isinstance(e["depends_on"], list):
        raise ValueError(f"{path}: depends_on must be a list for {entry_id}")
    for d in e.get("depends_on", []):
        if not isinstance(d, str) or not ID_RE.fullmatch(d) or \
                ".." in d or "\n" in d:
            raise ValueError(f"{path}: invalid depends_on id: {d!r}")
