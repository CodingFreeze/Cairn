"""board.jsonl control-plane storage (atomic, single-writer).

Validation rules (charsets, type checks, read-side fail-closed checks) live in
boardcheck.py; this module owns storage, locking, and CRUD.
"""
import contextlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from cairn_core import boardcheck
from cairn_core.boardcheck import (
    ID_RE as _ID_RE,                    # re-exported for legacy importers
    SETTABLE_FIELDS as _SETTABLE_FIELDS,
    VALID_STATUS,
    validate_settable as _validate_settable,
    validate_ticket_id as _validate_ticket_id,
)
from cairn_core.safepath import (
    assert_safe_root,
    atomic_write,
    open_lock_fd,
    safe_open_read,
    safe_mkdir,
)

try:  # advisory locking is POSIX-only; degrade to a no-op on Windows.
    import fcntl
except ImportError:  # pragma: no cover - exercised only on Windows
    fcntl = None

BOARD_FILENAME = "board.jsonl"
LOCK_FILENAME = "board.lock"

# Board/vault format version. Bumped on breaking layout changes; `cairn init`
# stamps it into .cairn/meta.json so future versions can detect/migrate.
FORMAT_VERSION = 2

# Per-process re-entrancy depth, keyed by the resolved lock path. flock() ties
# the lock to an open file description, so a second flock(LOCK_EX) on a NEW fd in
# the same process would block on itself. We therefore acquire the OS lock only at
# depth 0 and reference-count nested acquisitions. _DEPTH_MUTEX guards the dict's
# read-modify-write so two threads can't both see depth 0 and believe they hold
# the re-entrant lock simultaneously.
_LOCK_DEPTH = {}
_DEPTH_MUTEX = threading.Lock()


def _now():
    return datetime.now(timezone.utc).isoformat()


def board_path(cairn_dir):
    return Path(cairn_dir) / BOARD_FILENAME


@contextlib.contextmanager
def _board_lock(cairn_dir):
    """Advisory exclusive lock around a read-modify-write of the board.

    Uses fcntl.flock on .cairn/board.lock. On platforms without fcntl (Windows)
    this degrades to a no-op so behaviour is unchanged for single-process use.

    Guard order: assert_safe_root fires BEFORE the parent mkdir so a symlinked
    .cairn root cannot cause mkdir to create board.lock outside the repo.
    The lock file itself is opened with O_NOFOLLOW so a planted symlinked lock
    file is refused by the kernel.
    """
    if fcntl is None:
        yield
        return
    # Refuse a symlinked .cairn root BEFORE any mkdir or open.
    assert_safe_root(cairn_dir)
    lock = Path(cairn_dir) / LOCK_FILENAME
    safe_mkdir(cairn_dir, lock.parent)
    key = os.path.realpath(str(lock))
    with _DEPTH_MUTEX:
        depth = _LOCK_DEPTH.get(key, 0)
        if depth > 0:
            # Already held by this process — re-enter without re-acquiring.
            _LOCK_DEPTH[key] = depth + 1
            reenter = True
        else:
            reenter = False
    if reenter:
        try:
            yield
        finally:
            with _DEPTH_MUTEX:
                _LOCK_DEPTH[key] -= 1
        return
    # open_lock_fd is dir-fd-anchored: it refuses a symlinked .cairn root AND a
    # symlinked board.lock (O_NOFOLLOW) with no pathname re-resolution to race.
    fd = open_lock_fd(cairn_dir, LOCK_FILENAME)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        with _DEPTH_MUTEX:
            _LOCK_DEPTH[key] = 1
        yield
    finally:
        with _DEPTH_MUTEX:
            _LOCK_DEPTH[key] = 0
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def read_board(cairn_dir):
    # safe_open_read is dir-fd-anchored: a symlinked .cairn root or board.jsonl
    # (or a swapped parent) is refused at the fd level — no path re-resolution to
    # race, so a planted symlink can never be followed to leak an outside file.
    p = board_path(cairn_dir)
    if not os.path.lexists(str(p)):
        return []
    entries = []
    with safe_open_read(cairn_dir, p) as fh:
        raw = fh.read()
    for lineno, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if line:
            try:
                e = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{p}:{lineno}: invalid json: {exc}") from exc
            # SECURITY: fail-closed per-entry validation on every read so a
            # hand-edited or committed board.jsonl cannot introduce an unsafe
            # id/status/branch/depends_on into the control plane.
            boardcheck.validate_read_entry(p, e)
            entries.append(e)
    # SECURITY: fail closed on duplicate ids. A hand-edited board.jsonl with two
    # entries for the same id would otherwise be collapsed last-write-wins by
    # resolve.next_ready, so a duplicate (e.g. T01 marked 'merged') could wrongly
    # unblock dependents while the real ticket is still todo/blocked.
    seen = set()
    for e in entries:
        eid = e["id"]
        if eid in seen:
            raise ValueError(f"{p}: duplicate ticket id: {eid!r}")
        seen.add(eid)
    return entries


def write_board(cairn_dir, entries):
    # Callers (add_entry/set_fields) hold _board_lock around the full read-modify-write; do not lock here (avoids double-acquire).
    # atomic_write is renameat-anchored: it creates a unique sibling temp in the
    # validated parent dir fd, fsyncs it, then renames onto board.jsonl with
    # src_dir_fd/dst_dir_fd (no pathname re-resolution to race), and fsyncs the
    # dir for durability. A symlinked .cairn root or symlinked board.jsonl is
    # refused at the fd level. Behaviour (sorted keys, atomicity) is identical.
    p = board_path(cairn_dir)
    text = "".join(json.dumps(e, sort_keys=True) + "\n" for e in entries)
    atomic_write(cairn_dir, p, text)


def add_entry(cairn_dir, entry, now=None):
    ticket_id = entry.get("id")
    # SECURITY: ticket id becomes part of filesystem paths (.cairn/worktrees/<id>) and
    # git refs (cairn/<id>). Restrict to a safe charset so an id cannot inject path
    # traversal ('/', '..') or a leading '-' (git option) — see codex worktree finding.
    _validate_ticket_id(ticket_id)
    e = {
        "id": entry["id"],
        "status": entry.get("status", "todo"),
        "branch": entry.get("branch"),
        "pr": entry.get("pr"),
        "depends_on": entry.get("depends_on", []),
        "owner": entry.get("owner"),
        "files_owned": entry.get("files_owned", []),
        "updated": now or _now(),
    }
    if "base_sha" in entry:
        e["base_sha"] = entry["base_sha"]
    # Data-contract fields are optional and only stored when supplied, so existing
    # boards (and tickets with no schema role) keep their byte-for-byte shape.
    for k in ("schema", "produces", "consumes"):
        if k in entry:
            e[k] = entry[k]
    # Full type-validation of every settable field present on the constructed entry.
    _validate_settable({k: e[k] for k in _SETTABLE_FIELDS if k in e})
    # Same invariant as set_fields: an entry born 'dispatched' must carry base_sha
    # (and gets dispatched_at), or resume classification can misread it.
    if e["status"] == "dispatched":
        if not e.get("base_sha"):
            raise ValueError(
                f"{ticket_id}: status=dispatched requires base_sha "
                "(record the base tip at dispatch)"
            )
        e["dispatched_at"] = now or _now()
    with _board_lock(cairn_dir):
        entries = read_board(cairn_dir)
        if any(x["id"] == entry["id"] for x in entries):
            raise ValueError(f"duplicate ticket id: {entry['id']}")
        entries.append(e)
        write_board(cairn_dir, entries)
    return e


def get_entry(cairn_dir, ticket_id):
    for e in read_board(cairn_dir):
        if e["id"] == ticket_id:
            return e
    return None


def set_fields(cairn_dir, ticket_id, fields, now=None):
    # Validate field names before touching the board
    for k in fields:
        if k not in _SETTABLE_FIELDS:
            raise KeyError(f"field not settable: {k}")

    # Type-validate values (shared with add_entry)
    _validate_settable(fields)

    with _board_lock(cairn_dir):
        entries = read_board(cairn_dir)
        for e in entries:
            if e["id"] == ticket_id:
                # INVARIANT: the todo->dispatched transition must record base_sha.
                # classify_ticket_state's empty-branch and FF-merge detection both
                # key off it — without it, resume can misclassify unfinished work
                # as merged. Reject the transition unless base_sha arrives with it
                # or is already present on the entry.
                if fields.get("status") == "dispatched":
                    if not (fields.get("base_sha") or e.get("base_sha")):
                        raise ValueError(
                            f"{ticket_id}: status=dispatched requires base_sha "
                            "(record the base tip at dispatch: "
                            "base_sha=$(git rev-parse <base>))"
                        )
                    # Stamp dispatch time for staleness detection (cairn status /
                    # reconcile flag long-running dispatches). Internal field —
                    # not settable directly.
                    e["dispatched_at"] = now or _now()
                e.update(fields)
                e["updated"] = now or _now()
                write_board(cairn_dir, entries)
                return e
    raise KeyError(ticket_id)


def remove_entry(cairn_dir, ticket_id, force=False):
    """Remove a ticket from the board.

    Refuses (ValueError) if other tickets depend on it and are not yet
    merged/cancelled — removing a live dependency would silently change
    next_ready ordering. `force=True` overrides (the CLI surfaces the
    dependent list so the operator decides).
    """
    _validate_ticket_id(ticket_id)
    with _board_lock(cairn_dir):
        entries = read_board(cairn_dir)
        if not any(e["id"] == ticket_id for e in entries):
            raise KeyError(ticket_id)
        dependents = [
            e["id"] for e in entries
            if ticket_id in e.get("depends_on", [])
            and e.get("status") not in ("merged", "cancelled")
        ]
        if dependents and not force:
            raise ValueError(
                f"{ticket_id} has live dependents: {', '.join(sorted(dependents))} "
                "(cancel/remove them first, or pass --force)"
            )
        entries = [e for e in entries if e["id"] != ticket_id]
        write_board(cairn_dir, entries)
        return {"removed": ticket_id, "dependents": sorted(dependents)}
