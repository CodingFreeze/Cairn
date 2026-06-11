"""`cairn vault compact` — deterministic, LLM-free vault compaction.

Vault files are append-only journals; over months they grow past what a
session should load as context. Compaction trims them without losing memory:

  1. dedupe exact-duplicate bullet lines (keep the FIRST occurrence),
  2. move all but the newest N bullets (default 50; append-only order means
     last == newest) to .cairn/vault/archive/<name>-archive.md — append-only,
     with a timestamped header per compaction, never clobbered,
  3. rewrite the live file as: original head + a one-line pointer to the
     archive + the kept tail.

Dry-run by default (prints a summary, writes nothing); apply=True writes the
live file atomically via safepath and appends to the archive. Unknown vault
names are refused via vaultio.resolve_vault_file (the VAULT_FILES whitelist).

Parsing model: a bullet is any line whose lstrip starts with "- " (the same
rule vaultio.search uses); everything before the first bullet is the head.
Blank separators between bullets are dropped; a stray non-bullet line after
bullets begin is preserved into the head rather than lost.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

from cairn_core import vaultio
from cairn_core.safepath import (
    atomic_write,
    safe_mkdir,
    safe_open_append,
    safe_open_read,
)

DEFAULT_KEEP = 50
_POINTER_PREFIX = "> Older entries archived to "


def _now():
    return datetime.now(timezone.utc).isoformat()


def _pointer(name):
    return (f"{_POINTER_PREFIX}archive/{name}-archive.md "
            f"by `cairn vault compact`.")


def _parse(raw):
    """Split raw text into (head_lines, bullet_lines).

    Existing pointer lines are excluded from the head so re-compaction stays
    idempotent (exactly one pointer line in the rewritten file).
    """
    head, bullets = [], []
    for line in raw.splitlines():
        if line.lstrip().startswith("- "):
            bullets.append(line.strip())
        elif line.startswith(_POINTER_PREFIX):
            continue  # re-added on rewrite — never duplicated
        elif bullets and not line.strip():
            continue  # blank separator between appended bullets
        else:
            head.append(line)
    return head, bullets


def plan(cairn_dir, name, keep=DEFAULT_KEEP):
    """Compute the compaction (read-only). Raises ValueError on unknown name."""
    if not isinstance(keep, int) or keep < 0:
        raise ValueError(f"--keep must be a non-negative integer, got: {keep!r}")
    live = vaultio.resolve_vault_file(cairn_dir, name)  # whitelist gate
    raw = ""
    if os.path.lexists(str(live)):
        with safe_open_read(cairn_dir, live) as fh:
            raw = fh.read()
    head, bullets = _parse(raw)
    seen, deduped = set(), []
    for b in bullets:
        if b not in seen:
            seen.add(b)
            deduped.append(b)
    n_arch = max(len(deduped) - keep, 0)
    return {
        "name": name, "live": live, "head": head, "total": len(bullets),
        "duplicates": len(bullets) - len(deduped),
        "archived": deduped[:n_arch], "kept": deduped[n_arch:],
        "archive": Path(cairn_dir) / "vault" / "archive" / f"{name}-archive.md",
    }


def apply_plan(cairn_dir, p, now=None):
    """Write the compaction: archive append (timestamped header per run, never
    clobbered), then atomic rewrite of the live file via safepath."""
    if p["archived"]:
        safe_mkdir(cairn_dir, p["archive"].parent)
        fresh = not os.path.lexists(str(p["archive"]))
        with safe_open_append(cairn_dir, p["archive"]) as fh:
            if fresh:
                fh.write(f"# {p['name']} — archive (append-only; written by "
                         "`cairn vault compact`)\n")
            fh.write(f"\n## Compacted {now or _now()} — "
                     f"{len(p['archived'])} entr"
                     f"{'y' if len(p['archived']) == 1 else 'ies'}\n\n")
            fh.write("\n".join(p["archived"]) + "\n")
    head = "\n".join(p["head"]).rstrip("\n")
    parts = [head] if head else []
    # The one-line pointer: only once an archive exists to point at.
    if p["archived"] or os.path.lexists(str(p["archive"])):
        parts.append(_pointer(p["name"]))
    if p["kept"]:
        parts.append("\n".join(p["kept"]))
    atomic_write(cairn_dir, p["live"], "\n\n".join(parts) + "\n")


def run(cairn_dir, name, keep=DEFAULT_KEEP, apply=False, now=None):
    """CLI entry: plan (and write when apply=True), return the summary."""
    p = plan(cairn_dir, name, keep=keep)
    changed = p["duplicates"] or p["archived"]
    out = [f"vault compact {name}: {p['total']} bullet(s), "
           f"{p['duplicates']} exact duplicate(s) removed, "
           f"{len(p['archived'])} archived, {len(p['kept'])} kept (keep={keep})"]
    if not changed:
        out.append("  nothing to compact — live file left untouched")
        return "\n".join(out)
    out.append(f"  archive: {p['archive']}")
    if apply:
        apply_plan(cairn_dir, p, now=now)
        out.append("applied: live file rewritten atomically; archived entries "
                   "appended")
    else:
        out.append("dry-run: nothing written (re-run with --apply)")
    return "\n".join(out)
