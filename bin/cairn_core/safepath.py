"""Symlink/escape guards for .cairn writes and reads.

A malicious repo could plant a symlink under .cairn/ so an auto-running hook
reads, appends to, or overwrites files OUTSIDE the repo. These helpers refuse to
follow any symlink and refuse any path that escapes the cairn root.

SECURITY MODEL — openat-style dir-fd-anchored traversal (closes the TOCTOU
symlink-race class):
    The old approach validated the parent chain with `ensure_within()` and then
    opened the path BY NAME. O_NOFOLLOW only protects the FINAL component, so a
    raced swap of a *parent* directory (e.g. `.cairn/handoff` or `.cairn/vault`)
    to a symlink BETWEEN the check and the open could still escape the root.

    We now walk to the parent one component at a time from a file descriptor
    rooted at realpath(.cairn), opening each intermediate with
    O_DIRECTORY|O_NOFOLLOW via `dir_fd=`. Once we hold the parent fd, the final
    open/unlink/mkdir is performed relative to that fd (`dir_fd=parent_fd`) so
    there is NO path re-resolution left to race: the kernel cannot be tricked
    into following a symlink that was swapped in after our checks.

    `assert_safe_root`/`ensure_within` are kept as cheap pre-checks and for
    callers that still use them, but the SECURITY now comes from the anchored
    fds, not the pre-check.

FALLBACK: on exotic platforms where `dir_fd=` is unsupported
(`os.open not in os.supports_dir_fd`), we fall back to the previous
`ensure_within` + O_NOFOLLOW behavior so the code still runs. On macOS/Linux the
anchored path is always used.
"""
import os

# Dir-fd-anchored (openat/renameat) primitives live in safepath_fd to keep both
# modules under the 300-line cap. Re-exported here so callers and tests keep
# using the `safepath.` namespace (e.g. safepath._walk_to_parent, safepath
# .atomic_write, safepath.open_lock_fd). See safepath_fd for the full security
# model + the documented fallback (residual TOCTOU only on platforms lacking
# os.supports_dir_fd — none of the mainstream ones).
from cairn_core.safepath_fd import (  # noqa: F401
    _SUPPORTS_DIR_FD,
    _resolve_root,
    _rel_parts,
    _walk_to_parent,
    open_dir_fd,
    open_lock_fd,
)
from cairn_core import safepath_fd as _fd


def ensure_within(cairn_dir, target_path):
    """Return the realpath of `target_path` if it is safely inside `cairn_dir`.

    Rejects (raises ValueError) if:
      - `target_path` itself is a symlink, OR
      - any existing parent component of `target_path` is a symlink, OR
      - the realpath of the parent directory is not within realpath(cairn_dir).

    The leaf may be nonexistent (we are about to create it); only the parent
    chain must resolve safely inside the root.

    NOTE: this is a cheap pre-check only. The real TOCTOU-safe guarantee comes
    from the dir-fd-anchored helpers below.
    """
    root = os.path.realpath(str(cairn_dir))
    target = os.path.abspath(str(target_path))

    # Refuse a symlinked final component outright.
    if os.path.islink(target):
        raise ValueError(f"refusing to follow symlink/escape: {target_path}")

    # Walk every existing parent component; reject if any is a symlink.
    parent = os.path.dirname(target)
    cur = parent
    seen = set()
    while cur and cur not in seen:
        seen.add(cur)
        if os.path.islink(cur):
            raise ValueError(f"refusing to follow symlink/escape: {target_path}")
        nxt = os.path.dirname(cur)
        if nxt == cur:
            break
        cur = nxt

    # The realpath of the parent must live within the realpath of the root.
    real_parent = os.path.realpath(parent)
    if real_parent != root and not real_parent.startswith(root + os.sep):
        raise ValueError(f"refusing to follow symlink/escape: {target_path}")

    return os.path.join(real_parent, os.path.basename(target))


def assert_safe_root(cairn_dir):
    """Validate that the `.cairn` root itself is not reached through a symlink.

    A malicious repo could ship `.cairn` as a symlink (or nest it under a
    symlinked ancestor) so that the auto-running hook reads/writes OUTSIDE the
    repo. Raise ValueError if the `.cairn` directory is a symlink. Return the
    realpath of the root so callers can route all subsequent I/O through it.
    """
    cairn = str(cairn_dir)
    if os.path.islink(cairn):
        raise ValueError(f"refusing: .cairn root is a symlink: {cairn_dir}")
    return os.path.realpath(cairn)


def atomic_write(cairn_dir, path, text):
    """Race-free atomic write of `text` to `path` (dir-fd-anchored renameat).

    Thin wrapper over safepath_fd.atomic_write that wires in `ensure_within` for
    the documented fallback used only on platforms lacking dir_fd support. On
    every mainstream platform the anchored (renameat) path is taken — no pathname
    re-resolution is left to race.
    """
    return _fd.atomic_write(cairn_dir, path, text, ensure_within=ensure_within)


def safe_open_read(cairn_dir, path):
    """Open `path` for reading, refusing any symlinked component or escape.

    Walks to the parent via dir fds, then opens the leaf with O_NOFOLLOW relative
    to the validated parent fd. Returns an open text file object the caller is
    responsible for closing.
    """
    if not _SUPPORTS_DIR_FD:
        # Fallback for exotic platforms without dir_fd support.
        assert_safe_root(cairn_dir)
        ensure_within(cairn_dir, path)
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
        return os.fdopen(fd, "r", encoding="utf-8")
    parent_fd, name = _walk_to_parent(cairn_dir, path)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except OSError as e:
        os.close(parent_fd)
        raise ValueError(f"refusing to follow symlink/escape: {path} ({e})") from e
    os.close(parent_fd)
    return os.fdopen(fd, "r", encoding="utf-8")


def safe_open_write_create(cairn_dir, path):
    """Open `path` for writing (create/truncate), refusing symlinks/escape.

    O_NOFOLLOW (relative to the validated parent fd) refuses a symlinked leaf, so
    a planted symlinked leaf cannot be followed to clobber an outside file.
    """
    if not _SUPPORTS_DIR_FD:
        assert_safe_root(cairn_dir)
        ensure_within(cairn_dir, path)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
        fd = os.open(str(path), flags, 0o644)
        return os.fdopen(fd, "w", encoding="utf-8")
    parent_fd, name = _walk_to_parent(cairn_dir, path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, 0o644, dir_fd=parent_fd)
    except OSError as e:
        os.close(parent_fd)
        raise ValueError(f"refusing to follow symlink/escape: {path} ({e})") from e
    os.close(parent_fd)
    return os.fdopen(fd, "w", encoding="utf-8")


def safe_open_append(cairn_dir, path):
    """Open `path` for appending (create if missing), refusing symlinks/escape.

    Append mode cannot clobber prior content; the dir-fd anchoring + O_NOFOLLOW
    refuses a symlinked leaf or parent.
    """
    if not _SUPPORTS_DIR_FD:
        assert_safe_root(cairn_dir)
        ensure_within(cairn_dir, path)
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW
        fd = os.open(str(path), flags, 0o644)
        return os.fdopen(fd, "a", encoding="utf-8")
    parent_fd, name = _walk_to_parent(cairn_dir, path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, 0o644, dir_fd=parent_fd)
    except OSError as e:
        os.close(parent_fd)
        raise ValueError(f"refusing to follow symlink/escape: {path} ({e})") from e
    os.close(parent_fd)
    return os.fdopen(fd, "a", encoding="utf-8")


def safe_unlink(cairn_dir, path):
    """Unlink `path`, anchored to its validated parent fd (no path re-resolution)."""
    if not _SUPPORTS_DIR_FD:
        assert_safe_root(cairn_dir)
        ensure_within(cairn_dir, path)
        if not os.path.islink(str(path)):
            os.unlink(str(path))
        return
    parent_fd, name = _walk_to_parent(cairn_dir, path)
    try:
        os.unlink(name, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)


def safe_mkdir(cairn_dir, path):
    """Create `path` (and parents) anchored to dir fds; refuse symlinked parts.

    Walks component-by-component from the root fd. For each component we try to
    open it as a directory (O_DIRECTORY|O_NOFOLLOW); on FileNotFoundError we
    mkdir it relative to the current fd then open it. A symlinked existing
    component raises OSError → ValueError. All fds are closed in a finally.
    Returns the realpath of the created directory.
    """
    if not _SUPPORTS_DIR_FD:
        # Fallback: legacy whole-path validation + makedirs.
        root = assert_safe_root(cairn_dir)
        target = os.path.abspath(str(path))
        if target != root and not target.startswith(root + os.sep):
            raise ValueError(f"refusing: mkdir outside cairn root: {path}")
        cur = target
        seen = set()
        while cur and cur not in seen:
            seen.add(cur)
            if os.path.lexists(cur) and os.path.islink(cur):
                raise ValueError(f"refusing to follow symlink/escape: {path}")
            if cur == root:
                break
            nxt = os.path.dirname(cur)
            if nxt == cur:
                break
            cur = nxt
        os.makedirs(target, exist_ok=True)
        return target

    root = _resolve_root(cairn_dir)
    # The root (.cairn) may not exist yet on first scaffold. Create it directly;
    # _resolve_root already refused a symlinked .cairn, and realpath normalised
    # the path, so makedirs here builds the symlink-free root we anchor to.
    os.makedirs(root, exist_ok=True)
    target = os.path.abspath(str(path))
    if target == root:
        return root  # root already validated as a real dir
    _, parts = _rel_parts(cairn_dir, path)

    dir_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for comp in parts:
            try:
                nfd = os.open(
                    comp,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=dir_fd,
                )
            except FileNotFoundError:
                os.mkdir(comp, 0o755, dir_fd=dir_fd)
                nfd = os.open(
                    comp,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=dir_fd,
                )
            except OSError as e:
                raise ValueError(
                    f"refusing to follow symlink/escape: {path} ({e})"
                ) from e
            os.close(dir_fd)
            dir_fd = nfd
    finally:
        os.close(dir_fd)
    return target
