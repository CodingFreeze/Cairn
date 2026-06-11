"""Build a portable resume pack from board.jsonl + vault files."""
import json
import os
from pathlib import Path

from cairn_core.safepath import (
    assert_safe_root,
    atomic_write,
    safe_open_read,
    safe_mkdir,
)

OPEN_STATUSES = {"todo", "dispatched", "in-progress", "pr-open", "blocked"}


def _read_board(cairn_dir):
    p = Path(cairn_dir) / "board.jsonl"
    if not os.path.lexists(str(p)):
        return []
    # safe_open_read is dir-fd-anchored: a symlinked board.jsonl or parent is
    # refused at the fd level (no path re-resolution to race).
    out = []
    with safe_open_read(cairn_dir, p) as fh:
        raw = fh.read()
    for line in raw.splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _read_vault(cairn_dir, name):
    p = Path(cairn_dir) / "vault" / f"{name}.md"
    if not os.path.lexists(str(p)):
        return ""
    # Refuse to follow a symlinked source escaping the cairn root — skip it.
    # safe_open_read anchors to validated dir fds, so a symlinked vault file or
    # parent raises (caught here) rather than leaking an outside file.
    try:
        with safe_open_read(cairn_dir, p) as fh:
            return fh.read()
    except (ValueError, OSError):
        return ""


def recent_tail(text, n=5):
    """Return the last `n` non-empty `- ` bullet lines of a vault file, oldest-first."""
    bullets = [ln for ln in text.splitlines() if ln.strip().startswith("- ")]
    return "\n".join(bullets[-n:])


def _board_summary(entries):
    if not entries:
        return "No tickets on board."
    rows = []
    for e in sorted(entries, key=lambda x: x["id"]):
        deps = ",".join(e.get("depends_on", [])) or "-"
        branch = e.get("branch") or "-"
        rows.append(f"- {e['id']}  [{e['status']}]  deps={deps}  branch={branch}")
    return "\n".join(rows)


def build_pack(cairn_dir):
    """Assemble the full handoff markdown string."""
    # Refuse a symlinked .cairn root before reading any board/vault file.
    assert_safe_root(cairn_dir)
    entries = _read_board(cairn_dir)
    open_tickets = [e for e in sorted(entries, key=lambda x: x["id"])
                    if e.get("status") in OPEN_STATUSES]
    open_lines = "\n".join(f"- {e['id']}  [{e['status']}]" for e in open_tickets) or "_(none)_"
    decisions = recent_tail(_read_vault(cairn_dir, "decisions"), n=5) or "_(none)_"
    issues = recent_tail(_read_vault(cairn_dir, "issues"), n=5) or "_(none)_"
    return (
        "# Cairn Handoff — portable resume pack\n\n"
        "> Drop this into a fresh Claude Code / Cursor / Codex session to resume cleanly.\n\n"
        "## Board summary\n"
        f"{_board_summary(entries)}\n\n"
        "## Open tickets\n"
        f"{open_lines}\n\n"
        "## Recent decisions\n"
        f"{decisions}\n\n"
        "## Recent issues / remedies\n"
        f"{issues}\n"
    )


def write_pack(cairn_dir):
    """Write the pack to handoff/latest.md and return its path.

    Refuses to follow a symlinked latest.md (or symlinked parent) escaping the
    cairn root. Writes via atomic_write, which is renameat-anchored: it creates a
    unique sibling temp in the validated parent dir fd, fsyncs it, then renames
    onto latest.md with src_dir_fd/dst_dir_fd (no pathname re-resolution to race)
    and fsyncs the dir for durability.
    """
    out = Path(cairn_dir) / "handoff" / "latest.md"
    # safe_mkdir is dir-fd-anchored: a symlinked .cairn root or symlinked handoff
    # component is refused at the fd-traversal level before any dir is created,
    # closing the TOCTOU race where a parent is swapped to a symlink mid-op.
    assert_safe_root(cairn_dir)
    safe_mkdir(cairn_dir, out.parent)
    content = build_pack(cairn_dir)
    atomic_write(cairn_dir, out, content)
    return out
