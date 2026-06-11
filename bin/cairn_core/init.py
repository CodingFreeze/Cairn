"""Detect repo mode and scaffold the .cairn/ tree (idempotent, never clobbers)."""
import json
import os
from pathlib import Path

from cairn_core import board

from cairn_core.safepath import (
    assert_safe_root,
    ensure_within,
    safe_mkdir,
    safe_open_append,
    safe_open_read,
    safe_open_write_create,
)

_MANIFESTS = ["package.json", "pyproject.toml", "Cargo.toml", "go.mod", "pom.xml", "Gemfile"]
_SRC_DIRS = ["src", "lib", "app"]
_TEMPLATE_FILES = [
    "PROTOCOL.md",
    "vault/schema.md",
    "vault/decisions.md",
    "vault/issues.md",
    "vault/map.md",
]

# A cairn-managed .gitignore block at the repo ROOT. Without it a greenfield
# `git init` tracks build junk (e.g. __pycache__/*.pyc); when cairn-run rebases a
# worktree branch whose pyc main already deleted, git raises a spurious
# CONFLICT (modify/delete) on pure junk and derails the merge. The block is
# additive + marker-fenced so an existing repo's own rules are never clobbered.
_GI_BEGIN = "# >>> cairn managed (auto-added by `cairn init`) >>>"
_GI_END = "# <<< cairn managed <<<"
_GI_BASE = [
    ".cairn/worktrees/",
    "__pycache__/",
    "*.py[cod]",
    "*.egg-info/",
    ".eggs/",
    "build/",
    "dist/",
    "node_modules/",
    ".DS_Store",
]
# Stack-specific build dirs, added only when the manifest is present so we never
# ignore a legitimately-named source dir in an unrelated stack.
_GI_STACK = {"Cargo.toml": ["/target/"]}

# A cairn-managed .gitattributes INSIDE .cairn/ (patterns are relative to it).
# Vault + handoff files are append-only journals: when two team clones each add
# entries and the branches merge, union keeps BOTH sides instead of raising a
# textual conflict. board.jsonl is deliberately NOT union: union would
# concatenate both sides' lines and manufacture duplicate ticket ids, which
# read_board fails closed on — a board conflict must surface as a REAL conflict
# (one writer wins, then `cairn board doctor` repairs any merge debris) rather
# than silently merging into a corrupt control plane.
_GA_BEGIN = "# >>> cairn managed (auto-added by `cairn init`) >>>"
_GA_END = "# <<< cairn managed <<<"
_GA_LINES = [
    "# Append-only journals: union-merge keeps both clones' entries.",
    "# board.jsonl is deliberately NOT union — union would manufacture",
    "# duplicate ticket ids, which read_board fails closed on. Board",
    "# conflicts must surface as real conflicts (`cairn board doctor`).",
    "vault/*.md merge=union",
    "handoff/*.md merge=union",
]

_GOAL_TEMPLATE = """# Project goal

{goal}

---
_Seeded by `cairn init --goal`. Owned and refined by `/cairn-plan` — update this
file as the spec sharpens; it is the durable statement of what this project is for._
"""


def _gitignore_block(target):
    lines = list(_GI_BASE)
    for manifest, extra in _GI_STACK.items():
        if (Path(target) / manifest).exists():
            lines += extra
    return _GI_BEGIN + "\n" + "\n".join(lines) + "\n" + _GI_END + "\n"


def _scaffold_gitignore(target):
    """Ensure the repo-root .gitignore carries the cairn-managed block.

    Lives OUTSIDE .cairn, so the .cairn-scoped safepath writers do not apply;
    we use our own O_NOFOLLOW guard. Never clobbers an operator's existing rules:
    a missing file is created fresh; an existing file gets the managed block
    appended only when absent. A symlinked .gitignore is refused (a planted
    symlink could redirect the write outside the repo).
    """
    gi = Path(target) / ".gitignore"
    block = _gitignore_block(target)
    if os.path.lexists(str(gi)):
        # Read through an O_NOFOLLOW fd (no separate islink()+read_text(), which
        # leaves a TOCTOU window where the file could be swapped for a symlink
        # between the check and the read). O_NOFOLLOW refuses a symlinked leaf
        # outright, so both the read AND the append below stay inside the repo.
        try:
            rfd = os.open(str(gi), os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            return  # symlink (ELOOP) or vanished — refuse to follow
        with os.fdopen(rfd, "r", encoding="utf-8") as fh:
            existing = fh.read()
        if _GI_BEGIN in existing:
            return  # already managed — idempotent
        sep = "" if existing.endswith("\n") else "\n"
        try:
            wfd = os.open(str(gi), os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        except OSError:
            return  # raced into a symlink after the read — refuse
        with os.fdopen(wfd, "a", encoding="utf-8") as fh:
            fh.write(sep + "\n" + block)
        return
    try:
        fd = os.open(str(gi), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    except FileExistsError:
        return  # raced in after the lexists check — leave it for the operator
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(block)


def _scaffold_gitattributes(cairn):
    """Ensure .cairn/.gitattributes carries the cairn-managed union-merge block.

    Same idempotent, additive, marker-fenced contract as _scaffold_gitignore,
    but the file lives INSIDE .cairn so all I/O goes through the dir-fd-anchored
    safepath helpers (a planted symlinked leaf or parent is refused at the fd
    level). A missing file is created fresh; an existing file gets the managed
    block appended only when absent; operator rules are never clobbered.
    """
    ga = Path(cairn) / ".gitattributes"
    block = _GA_BEGIN + "\n" + "\n".join(_GA_LINES) + "\n" + _GA_END + "\n"
    if os.path.lexists(str(ga)):
        # safe_open_read refuses a symlinked leaf (O_NOFOLLOW) so a planted
        # symlink can neither be read through nor appended through.
        with safe_open_read(cairn, ga) as fh:
            existing = fh.read()
        if _GA_BEGIN in existing:
            return  # already managed — idempotent
        sep = "" if (not existing or existing.endswith("\n")) else "\n"
        with safe_open_append(cairn, ga) as fh:  # append mode cannot clobber
            fh.write(sep + "\n" + block)
        return
    with safe_open_write_create(cairn, ga) as fh:
        fh.write(block)


def detect_mode(target):
    target = Path(target)
    if (target / ".git").exists():
        return "existing"
    if any((target / m).exists() for m in _MANIFESTS):
        return "existing"
    if any((target / d).is_dir() for d in _SRC_DIRS):
        return "existing"
    return "greenfield"


def _write_if_absent(cairn, dest, content):
    """Write `content` to `dest` only if no entry exists there yet.

    Refuses to follow a planted symlinked leaf: if `dest` already exists (as a
    symlink or otherwise) we leave it untouched; if absent we write through the
    O_NOFOLLOW safe writer so a TOCTOU-planted symlink is still refused.
    """
    if os.path.lexists(str(dest)):
        # A planted symlinked leaf must NOT be written through. ensure_within
        # raises on a symlinked component; a real existing file is left as-is
        # (idempotent, never clobbers).
        ensure_within(cairn, dest)
        return
    with safe_open_write_create(cairn, dest) as fh:
        fh.write(content)


def scaffold(target, mode, templates_dir, goal=None):
    target = Path(target)
    templates_dir = Path(templates_dir)
    cairn = target / ".cairn"
    # If .cairn already exists, refuse a symlinked root BEFORE any mkdir/write so
    # a malicious planted symlink can never be scaffolded through to escape.
    if os.path.lexists(str(cairn)):
        assert_safe_root(cairn)
    safe_mkdir(cairn, cairn / "vault")
    safe_mkdir(cairn, cairn / "tickets")
    safe_mkdir(cairn, cairn / "handoff")
    safe_mkdir(cairn, cairn / "spec")
    for rel in _TEMPLATE_FILES:
        _write_if_absent(cairn, cairn / rel, (templates_dir / rel).read_text())
    _write_if_absent(cairn, cairn / "board.jsonl", "")
    _write_if_absent(cairn, cairn / ".mode", mode + "\n")
    # Format-version stamp so future cairn versions can detect/migrate old vaults.
    _write_if_absent(cairn, cairn / "meta.json",
                     json.dumps({"format": board.FORMAT_VERSION}) + "\n")
    if goal:
        # Persist the seed goal into the vault; /cairn-plan owns and refines it.
        _write_if_absent(cairn, cairn / "vault" / "goal.md", _GOAL_TEMPLATE.format(goal=goal))
    _scaffold_gitignore(target)
    _scaffold_gitattributes(cairn)
    return cairn
