"""Append-only vault writers. Single-writer rule: appends, never clobbers."""
import os
from datetime import datetime, timezone
from pathlib import Path

from cairn_core.safepath import (
    assert_safe_root,
    safe_open_read,
    safe_open_append,
    safe_mkdir,
)

# Whitelist of writable vault targets. Anything else is rejected (no traversal, no secrets file).
VAULT_FILES = {
    "schema": "schema.md",
    "decisions": "decisions.md",
    "issues": "issues.md",
    "map": "map.md",
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def resolve_vault_file(cairn_dir, name):
    """Map a logical vault name to its path. Rejects unknown names and path traversal."""
    if name not in VAULT_FILES:
        raise ValueError(f"unknown vault file: {name!r} (allowed: {sorted(VAULT_FILES)})")
    return Path(cairn_dir) / "vault" / VAULT_FILES[name]


def already_present(cairn_dir, name, text):
    """True if `text` already appears in the target file (cheap dedupe check).

    Reads through safe_open_read (O_NOFOLLOW) so a planted symlinked vault file
    cannot be followed to leak an outside file's contents.
    """
    p = resolve_vault_file(cairn_dir, name)
    if not os.path.lexists(str(p)):
        return False
    assert_safe_root(cairn_dir)
    with safe_open_read(cairn_dir, p) as fh:
        return text.strip() in fh.read()


def search(cairn_dir, query, scope=None, limit=20):
    """Ranked vault search (replaces the old single-substring grep).

    Splits `query` into terms; a bullet line matching MORE terms ranks higher,
    ties broken by recency (vault bullets are timestamp-prefixed, append-only,
    so later file position == newer). `scope` restricts to one logical vault
    file. Returns up to `limit` of (name, line) best-first.
    """
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return []
    names = [scope] if scope else list(VAULT_FILES)
    if scope and scope not in VAULT_FILES:
        raise ValueError(f"unknown vault file: {scope!r} (allowed: {sorted(VAULT_FILES)})")
    scored = []
    for name in names:
        p = resolve_vault_file(cairn_dir, name)
        if not os.path.lexists(str(p)):
            continue
        with safe_open_read(cairn_dir, p) as fh:
            lines = fh.read().splitlines()
        for pos, line in enumerate(lines):
            s = line.strip()
            if not s.startswith("- "):
                continue
            low = s.lower()
            hits = sum(1 for t in terms if t in low)
            if hits:
                scored.append((-hits, -pos, name, s))
    scored.sort()
    return [(name, line) for _, _, name, line in scored[:limit]]


def append(cairn_dir, name, text, now=None, dedupe=False):
    """Append a timestamped entry to a vault file. Creates the file if missing.

    Never rewrites or deletes prior content — opens in append mode only.
    """
    p = resolve_vault_file(cairn_dir, name)
    # The dir-fd-anchored helpers (safe_mkdir / safe_open_append) close the TOCTOU
    # symlink-race: a symlinked .cairn root or symlinked vault component is refused
    # at the fd-traversal level, so no directory is created or file opened through
    # a planted symlink even if a parent is swapped between checks.
    safe_mkdir(cairn_dir, p.parent)
    text = text.strip()
    if dedupe and already_present(cairn_dir, name, text):
        return False
    stamp = now or _now()
    entry = f"\n- {stamp} — {text}\n"
    with safe_open_append(cairn_dir, p) as fh:  # append mode cannot clobber
        fh.write(entry)
    return True
