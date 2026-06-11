"""Dir-fd-anchored (openat/renameat) primitives for safepath.

Split out of safepath.py to keep both modules under the 300-line cap. This holds
the low-level capability gate, root/parts resolution, the parent-fd walk, and the
Phase-11 final-commit helpers (atomic_write, open_dir_fd, open_lock_fd) that
anchor the rename/lock-open steps to validated directory file descriptors so no
pathname re-resolution is left to race.

SECURITY MODEL — openat/renameat-style dir-fd-anchored I/O (closes the TOCTOU
symlink-race class):
    Validating a parent chain with `ensure_within()` and then opening / renaming
    BY NAME leaves a window: O_NOFOLLOW only guards the FINAL component, so a
    raced swap of a *parent* directory to a symlink between the check and the
    syscall could still escape the root. We instead walk to the parent one
    component at a time from a descriptor rooted at realpath(.cairn), opening each
    intermediate with O_DIRECTORY|O_NOFOLLOW via `dir_fd=`. Once we hold the
    parent fd, the final open/unlink/mkdir/RENAME is performed relative to that fd
    (`dir_fd=` / `src_dir_fd=`/`dst_dir_fd=`) — the kernel cannot be tricked into
    following a symlink swapped in after our checks.

RESIDUAL FALLBACK — accepted risk:
    On exotic platforms WITHOUT `os.supports_dir_fd` for the needed syscalls
    (`_SUPPORTS_DIR_FD` is False — rare; macOS, Linux and the BSDs all support it)
    these operations fall back to check-then-open / mkstemp + os.replace by
    pathname. That fallback CANNOT fully close the parent-swap TOCTOU race: a
    sufficiently fast attacker could swap a parent directory to a symlink between
    the validation and the syscall. For a LOCAL, SINGLE-USER tool this is an
    accepted residual risk — the only platforms affected are ones that lack
    dir_fd support entirely, which are not realistic deployment targets. On every
    mainstream platform the anchored (race-free) path is always taken.
"""
import os
import stat as _stat

# Capability gate: dir_fd-anchored open/mkdir/unlink/rename need kernel + libc
# support. os.rename honours src_dir_fd/dst_dir_fd wherever os.open supports
# dir_fd, so we gate the whole anchored path on this single check.
_SUPPORTS_DIR_FD = (
    os.open in os.supports_dir_fd
    and os.mkdir in os.supports_dir_fd
    and os.unlink in os.supports_dir_fd
)


def _resolve_root(cairn_dir):
    """Refuse a symlinked .cairn root; return its realpath."""
    if os.path.islink(str(cairn_dir)):
        raise ValueError(f"refusing: .cairn root is a symlink: {cairn_dir}")
    return os.path.realpath(str(cairn_dir))


def _rel_parts(cairn_dir, path):
    """Return ``(root, parts)`` of `path` relative to the realpath'd root.

    Raises ValueError if `path` escapes the root or resolves to the root itself
    (we refuse to treat the root as a leaf).
    """
    root = _resolve_root(cairn_dir)
    rel = os.path.relpath(os.path.abspath(str(path)), root)
    if rel == os.pardir or rel.startswith(os.pardir + os.sep) or os.path.isabs(rel):
        raise ValueError(f"refusing: path escapes cairn root: {path}")
    if rel in (".", ""):
        raise ValueError(f"refusing to operate on the cairn root itself: {path}")
    parts = [p for p in rel.split(os.sep) if p not in ("", ".")]
    if not parts:
        raise ValueError(f"refusing to operate on the cairn root itself: {path}")
    return root, parts


def _walk_to_parent(cairn_dir, path):
    """Open dir fds component-by-component to the parent of `path`.

    Returns ``(parent_fd, leaf_name)``. The CALLER MUST CLOSE ``parent_fd``.

    Every intermediate component is opened with O_DIRECTORY|O_NOFOLLOW relative
    to the prior fd, so a symlinked component raises OSError (ELOOP) which we
    convert to ValueError. There is no path re-resolution left to race.
    """
    root, parts = _rel_parts(cairn_dir, path)
    leaf = parts[-1]
    intermediates = parts[:-1]

    dir_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for comp in intermediates:
            nfd = os.open(
                comp,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=dir_fd,
            )
            os.close(dir_fd)
            dir_fd = nfd
    except OSError as e:
        os.close(dir_fd)
        raise ValueError(f"refusing to follow symlink/escape: {path} ({e})") from e
    return dir_fd, leaf


def open_dir_fd(cairn_dir, *subparts):
    """Open and return an OS dir fd for ``<root>/<subparts...>``.

    Opens the realpath'd root with O_RDONLY|O_DIRECTORY|O_NOFOLLOW (refusing a
    symlinked .cairn) and walks each subpart with O_DIRECTORY|O_NOFOLLOW via
    ``dir_fd=`` — a symlinked component raises ValueError. The CALLER MUST CLOSE
    the returned fd.
    """
    root = _resolve_root(cairn_dir)
    dir_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for comp in subparts:
            if comp in ("", ".", os.pardir) or os.sep in comp:
                raise ValueError(f"refusing: invalid dir-fd subpart: {comp!r}")
            nfd = os.open(
                comp,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=dir_fd,
            )
            os.close(dir_fd)
            dir_fd = nfd
    except OSError as e:
        os.close(dir_fd)
        raise ValueError(
            f"refusing to follow symlink/escape: dir-fd {subparts} ({e})"
        ) from e
    except BaseException:
        os.close(dir_fd)
        raise
    return dir_fd


def _atomic_write_fallback(cairn_dir, path, text, ensure_within):
    """Best-effort atomic write for platforms lacking dir_fd support.

    Documented residual: check-then-open by pathname cannot fully close the
    parent-swap TOCTOU race. Used only when ``_SUPPORTS_DIR_FD`` is False.
    """
    import tempfile
    root = _resolve_root(cairn_dir)
    real = ensure_within(cairn_dir, path)
    if os.path.islink(real):
        raise ValueError(f"refusing to follow symlink/escape: {path}")
    parent = os.path.dirname(real)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix="." + os.path.basename(real) + ".",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, real)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        dfd = os.open(root, os.O_DIRECTORY)
        os.fsync(dfd)
        os.close(dfd)
    except OSError:
        pass


def atomic_write(cairn_dir, path, text, ensure_within=None):
    """Race-free atomic write of `text` to `path` (must resolve under the root).

    Opens the parent via dir fds, creates a unique sibling temp with
    O_CREAT|O_EXCL|O_NOFOLLOW, fsyncs it, then renameat's (os.replace with
    src_dir_fd/dst_dir_fd) onto the leaf — no pathname re-resolution to race.
    fsyncs the parent dir for durability. On error the temp is unlinked via the
    dir fd. Falls back to mkstemp + os.replace by pathname only where dir_fd is
    unsupported (documented residual risk).
    """
    if not _SUPPORTS_DIR_FD:
        if ensure_within is None:  # pragma: no cover - wired by safepath
            raise RuntimeError("atomic_write fallback requires ensure_within")
        _atomic_write_fallback(cairn_dir, path, text, ensure_within)
        return

    dfd, leaf = _walk_to_parent(cairn_dir, path)
    tmp = None
    try:
        # Hard-refuse a symlinked existing leaf, anchored to the validated parent
        # fd so the check itself cannot be raced. os.replace would otherwise
        # quietly REPLACE the symlink (not follow it) — but we'd rather refuse
        # outright than touch a planted symlinked destination.
        try:
            if _stat.S_ISLNK(os.lstat(leaf, dir_fd=dfd).st_mode):
                raise ValueError(f"refusing to follow symlink/escape: {path}")
        except FileNotFoundError:
            pass  # leaf does not exist yet — fine, we are creating it
        # Find a free unique temp name in the SAME dir as the leaf.
        n = 0
        while True:
            cand = f".{leaf}.{os.getpid()}.{n}.tmp"
            try:
                fd = os.open(
                    cand,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o644,
                    dir_fd=dfd,
                )
            except FileExistsError:
                n += 1
                continue
            tmp = cand
            break
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
        except BaseException:
            os.close(fd)  # fdopen failed before taking ownership
            raise
        # renameat: both ends anchored to the validated dir fd, no re-resolution.
        os.replace(tmp, leaf, src_dir_fd=dfd, dst_dir_fd=dfd)
        tmp = None  # consumed by the rename
        os.fsync(dfd)
    except BaseException:
        if tmp is not None:
            try:
                os.unlink(tmp, dir_fd=dfd)
            except OSError:
                pass
        raise
    finally:
        os.close(dfd)


def open_lock_fd(cairn_dir, lock_name):
    """Open (creating) `lock_name` in the .cairn root, anchored to a dir fd.

    Refuses a symlinked .cairn root (via open_dir_fd) and a symlinked lock file
    (O_NOFOLLOW). Returns an O_RDWR fd the CALLER MUST CLOSE.
    """
    if lock_name in ("", ".", os.pardir) or os.sep in lock_name:
        raise ValueError(f"refusing: invalid lock name: {lock_name!r}")
    dfd = open_dir_fd(cairn_dir)
    try:
        lfd = os.open(
            lock_name,
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o644,
            dir_fd=dfd,
        )
    except OSError as e:
        raise ValueError(
            f"refusing to follow symlink/escape: lock {lock_name} ({e})"
        ) from e
    finally:
        os.close(dfd)
    return lfd
