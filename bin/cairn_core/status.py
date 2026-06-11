"""Render the board as an aligned text table."""
from datetime import datetime, timezone

from cairn_core import resolve

_HEADER = ("ID", "STATUS", "DEPENDS_ON", "BRANCH")

# A dispatched/in-progress ticket older than this is flagged STALE — likely a
# hung or crashed subagent the operator should resume or re-dispatch.
STALE_AFTER_SECONDS = 2 * 60 * 60


def _stale_ids(entries, now=None):
    now = now or datetime.now(timezone.utc)
    out = []
    for e in entries:
        if e.get("status") not in ("dispatched", "in-progress"):
            continue
        ts = e.get("dispatched_at")
        if not ts:
            continue
        try:
            age = (now - datetime.fromisoformat(ts)).total_seconds()
        except ValueError:
            continue
        if age > STALE_AFTER_SECONDS:
            out.append((e["id"], int(age // 3600)))
    return out


def render(entries, now=None):
    if not entries:
        return "No tickets on board."
    rows = [_HEADER]
    for e in sorted(entries, key=lambda x: resolve.natural_key(x["id"])):
        rows.append((
            e["id"],
            e["status"],
            ",".join(e.get("depends_on", [])) or "-",
            e.get("branch") or "-",
        ))
    widths = [max(len(row[i]) for row in rows) for i in range(len(_HEADER))]
    table = "\n".join(
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
        for row in rows
    )

    # Append NOTE lines for tickets that depend on non-existent tickets
    notes = []
    for ticket_id, absent in sorted(resolve.missing_deps(entries).items()):
        notes.append(f"NOTE: {ticket_id} depends on missing ticket(s): {', '.join(absent)}")

    # Append a NOTE if a dependency cycle exists among not-merged tickets.
    cycle = resolve.find_cycle(entries)
    if cycle:
        notes.append(f"NOTE: dependency cycle detected among: {', '.join(cycle)}")

    # Flag dispatched/in-progress tickets whose dispatch is suspiciously old —
    # likely a hung/crashed subagent; resume with /cairn-resume or re-dispatch.
    for tid, hours in _stale_ids(entries, now=now):
        notes.append(f"NOTE: {tid} STALE — dispatched {hours}h ago with no merge; "
                     "resume or re-dispatch")

    if notes:
        return table + "\n" + "\n".join(notes)
    return table
