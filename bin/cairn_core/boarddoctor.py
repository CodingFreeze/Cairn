"""`cairn board doctor` — detect/repair board.jsonl damage from a team merge.

board.jsonl is deliberately NOT union-merged (see init._GA_LINES): the board is
last-write-wins state, not an append-only journal, so a textual merge can leave
exactly two damage states that read_board fails closed on:

  1. duplicate ticket ids — two clones each updated the same ticket and the
     merge kept both lines. Repair: keep the newest by `updated` (ISO-8601
     timestamps sort lexically; a missing `updated` sorts oldest; ties keep the
     later line), report every dropped line.
  2. malformed lines — conflict-marker debris, truncated JSON, or an entry that
     fails the read-side validation (boardcheck.validate_read_entry). Repair:
     report and quarantine the raw line to board.jsonl.rej (append-only, never
     clobbered) so nothing is silently destroyed.

Dry-run by default: diagnose and print, write nothing. With apply=True the
repaired board is rewritten atomically via safepath (renameat-anchored) under
the board lock, and quarantined lines are appended to board.jsonl.rej.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cairn_core import board, boardcheck
from cairn_core.safepath import atomic_write, safe_open_append, safe_open_read

REJ_FILENAME = "board.jsonl.rej"


def _now():
    return datetime.now(timezone.utc).isoformat()


def diagnose(cairn_dir):
    """Parse board.jsonl line-by-line, tolerating the damage read_board refuses.

    Returns {"keep": [entries, board order], "dropped": [(lineno, line, reason)],
    "quarantined": [(lineno, line, reason)]}. Read-only.
    """
    p = board.board_path(cairn_dir)
    raw = ""
    if os.path.lexists(str(p)):
        with safe_open_read(cairn_dir, p) as fh:
            raw = fh.read()
    parsed, quarantined = [], []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            e = json.loads(line)
            if not isinstance(e, dict):
                raise ValueError("not a JSON object")
            # Same fail-closed per-entry validation as read_board, so a repaired
            # board never reintroduces an unsafe id/status/branch/depends_on.
            boardcheck.validate_read_entry(p, e)
        except (ValueError, json.JSONDecodeError) as exc:
            quarantined.append((lineno, line, str(exc)))
            continue
        parsed.append((lineno, line, e))
    # Duplicate ids: keep the newest by `updated`; ties keep the later line
    # (later file position == later writer in an append/merge).
    best = {}
    for pos, (_, _, e) in enumerate(parsed):
        key = (e.get("updated") or "", pos)
        if e["id"] not in best or key > best[e["id"]][0]:
            best[e["id"]] = (key, pos)
    keep, dropped = [], []
    for pos, (lineno, line, e) in enumerate(parsed):
        if best[e["id"]][1] == pos:
            keep.append(e)
        else:
            dropped.append(
                (lineno, line, f"duplicate id {e['id']!r}, older `updated`"))
    return {"keep": keep, "dropped": dropped, "quarantined": quarantined}


def repair(cairn_dir, now=None):
    """Apply the repair under the board lock; returns the diagnosis acted on.

    Re-diagnoses INSIDE the lock so a concurrent writer cannot make the repair
    stale. Quarantined raw lines are appended (never clobbered) to
    board.jsonl.rej under a timestamped header; the repaired board is then
    rewritten atomically via safepath. A clean board is left byte-untouched.
    """
    with board._board_lock(cairn_dir):
        diag = diagnose(cairn_dir)
        if not diag["dropped"] and not diag["quarantined"]:
            return diag  # clean — do not rewrite a healthy board
        if diag["quarantined"]:
            rej = Path(cairn_dir) / REJ_FILENAME
            with safe_open_append(cairn_dir, rej) as fh:
                fh.write(f"# quarantined by `cairn board doctor` at "
                         f"{now or _now()}\n")
                for lineno, line, reason in diag["quarantined"]:
                    fh.write(f"# L{lineno}: {reason}\n{line}\n")
        text = "".join(
            json.dumps(e, sort_keys=True) + "\n" for e in diag["keep"])
        atomic_write(cairn_dir, board.board_path(cairn_dir), text)
    return diag


def render(diag, applied):
    """Human-readable report for the CLI."""
    keep, dropped, quar = diag["keep"], diag["dropped"], diag["quarantined"]
    out = [f"board doctor: {len(keep)} entr{'y' if len(keep) == 1 else 'ies'} "
           f"kept, {len(dropped)} duplicate(s) dropped, "
           f"{len(quar)} malformed line(s) quarantined"]
    for lineno, line, reason in dropped:
        out.append(f"  drop L{lineno} ({reason}): {line}")
    for lineno, line, reason in quar:
        out.append(f"  quarantine L{lineno} ({reason}): {line}")
    if not dropped and not quar:
        out.append("  board is clean — nothing to repair")
    elif applied:
        out.append(f"applied: board.jsonl rewritten"
                   f"{'; rejects appended to ' + REJ_FILENAME if quar else ''}")
    else:
        out.append("dry-run: nothing written (re-run with --apply to repair)")
    return "\n".join(out)


def run(cairn_dir, apply=False, now=None):
    """CLI entry: diagnose (and repair when apply=True), return the report."""
    diag = repair(cairn_dir, now=now) if apply else diagnose(cairn_dir)
    return render(diag, applied=apply)
