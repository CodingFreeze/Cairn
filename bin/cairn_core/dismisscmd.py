"""Dismiss/harvest command logic (moved out of bin/cairn for the 300-line cap).

Shared path for `cairn dismiss` (interactive) and `cairn harvest-candidates`
(SessionEnd hook): validate -> filter -> append to vault -> refresh handoff.
"""
import json

from cairn_core import dismiss_filter, handoff, vaultio
from cairn_core.safepath import safe_open_read, safe_unlink


def dismiss_candidates(cairn_dir, candidates):
    """Validate, filter, append to vault, refresh handoff.

    Returns the list of captured candidates so callers can report or stay
    silent. Raises ValueError / json.JSONDecodeError on bad input.
    """
    dismiss_filter.validate_candidates(candidates)
    existing = {}
    for name in ("decisions", "issues", "schema", "map"):
        p = cairn_dir / "vault" / f"{name}.md"
        if p.exists():
            with safe_open_read(cairn_dir, p) as fh:
                existing[name] = fh.read()
        else:
            existing[name] = ""
    kept = dismiss_filter.filter_candidates(candidates, existing=existing)
    captured = []
    for c in kept:
        if vaultio.append(cairn_dir, c["kind"], c["text"], dedupe=True):
            captured.append(c)
    handoff.write_pack(cairn_dir)  # refresh resume pack with harvested memory
    return captured


def harvest(cairn_dir):
    """Read, process, and safely delete handoff/dismiss-candidates.json.

    Called by the SessionEnd hook instead of shell cat/rm so all I/O goes
    through the safepath guards (symlinked parent dir or leaf both rejected).
    Returns None silently if the staging file does not exist. ValueError from
    path guards or invalid JSON propagates to the caller.
    """
    cand_path = cairn_dir / "handoff" / "dismiss-candidates.json"
    if not cand_path.exists():
        return None  # nothing staged
    with safe_open_read(cairn_dir, cand_path) as fh:
        raw = fh.read()
    candidates = json.loads(raw)  # caller maps decode errors to exit message
    captured = dismiss_candidates(cairn_dir, candidates)
    # Anchored unlink: no path re-resolution to race; symlinked leaf/parent refused.
    safe_unlink(cairn_dir, cand_path)
    return captured
