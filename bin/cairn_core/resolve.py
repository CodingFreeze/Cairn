"""Next-ready ticket resolution over the dependency DAG."""
import re

_DIGITS = re.compile(r"(\d+)")


def natural_key(ticket_id):
    """Natural-sort key: digit runs compare numerically, so T2 < T10.

    Plain lexicographic sort puts 'T10' before 'T2'; with zero-padded ids
    (T01..T09) that happens to work, but the board allows any id matching
    the safe charset, so unpadded ids would silently execute out of order.
    """
    return tuple(
        int(part) if part.isdigit() else part
        for part in _DIGITS.split(ticket_id)
    )


def next_ready(entries):
    """Return the lowest-id todo ticket whose dependencies are all merged, else None.

    A 'cancelled' dependency NEVER satisfies readiness — its dependents stay
    blocked until the operator removes the edge or cancels them too (treating
    cancelled like merged would wrongly unblock work whose input never landed).
    """
    by_id = {e["id"]: e for e in entries}
    for e in sorted(entries, key=lambda x: natural_key(x["id"])):
        if e["status"] != "todo":
            continue
        deps = e.get("depends_on", [])
        if all(by_id.get(d, {}).get("status") == "merged" for d in deps):
            return e["id"]
    return None


def ready_all(entries):
    """Return ALL todo tickets whose dependencies are all merged, natural-sorted.

    Same readiness rule as next_ready: a 'cancelled' or 'blocked' dependency
    does NOT satisfy readiness — only 'merged' does.
    """
    by_id = {e["id"]: e for e in entries}
    out = []
    for e in sorted(entries, key=lambda x: natural_key(x["id"])):
        if e["status"] != "todo":
            continue
        deps = e.get("depends_on", [])
        if all(by_id.get(d, {}).get("status") == "merged" for d in deps):
            out.append(e["id"])
    return out


def _paths_overlap(a, b):
    """True if path a conflicts with path b: equal, or one is a directory
    prefix of the other (compared with a trailing-slash prefix check)."""
    a, b = a.rstrip("/"), b.rstrip("/")
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def parallel_safe(entries, ready_ids):
    """Filter ready_ids to a prefix-greedy subset with pairwise-disjoint files_owned.

    A ticket with EMPTY files_owned conflicts with everything — it could touch
    any file — so it is only safe scheduled alone (included only as the
    first/only pick). Greedy in natural_key order: take the first ready ticket,
    then each next one only if its files are disjoint with ALL taken so far.
    """
    by_id = {e["id"]: e for e in entries}
    taken, taken_files = [], []
    for tid in sorted(ready_ids, key=natural_key):
        files = by_id.get(tid, {}).get("files_owned", []) or []
        if not files:
            if not taken:
                return [tid]  # wildcard ticket runs alone
            continue
        if any(_paths_overlap(f, g) for f in files for g in taken_files):
            continue
        taken.append(tid)
        taken_files.extend(files)
    return taken


def cancel_impact(entries, ticket_id):
    """Return ids of live (not merged/cancelled) tickets transitively dependent
    on `ticket_id` — the set the operator must decide about when cancelling."""
    rdeps = {}
    for e in entries:
        for d in e.get("depends_on", []):
            rdeps.setdefault(d, []).append(e["id"])
    by_id = {e["id"]: e for e in entries}
    seen, stack, out = set(), [ticket_id], []
    while stack:
        cur = stack.pop()
        for dep in rdeps.get(cur, []):
            if dep in seen:
                continue
            seen.add(dep)
            if by_id.get(dep, {}).get("status") not in ("merged", "cancelled"):
                out.append(dep)
            stack.append(dep)
    return sorted(out, key=natural_key)


def find_cycle(entries, include_merged=False):
    """Return a list of ticket ids forming a dependency cycle, or [] if acyclic.

    By default (include_merged=False) considers only not-merged tickets — a merged
    dependency is integrated and can never close a *live* (schedulable) cycle, which
    is the right view for next-ready resolution. Performs an iterative DFS over
    depends_on edges and returns the ids on the back-edge cycle. Missing dep targets
    (and, when include_merged is False, merged ones) are ignored.

    With include_merged=True every ticket is considered regardless of status. The
    spec graph renders ALL tickets+edges, so a cycle that passes through a merged
    ticket is visually present; this flag lets the graph surface it as a warning.
    """
    by_id = {e["id"]: e for e in entries}
    if include_merged:
        live = set(by_id)
    else:
        live = {i for i, e in by_id.items() if e.get("status") != "merged"}
    WHITE, GREY, BLACK = 0, 1, 2
    color = {i: WHITE for i in live}

    def deps(i):
        return [d for d in by_id[i].get("depends_on", []) if d in live]

    for root in sorted(live):
        if color[root] != WHITE:
            continue
        stack = [(root, iter(deps(root)))]
        path = [root]
        color[root] = GREY
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                if color[nxt] == GREY:
                    # Back edge → cycle from nxt up to the current node.
                    idx = path.index(nxt)
                    return path[idx:]
                if color[nxt] == WHITE:
                    color[nxt] = GREY
                    path.append(nxt)
                    stack.append((nxt, iter(deps(nxt))))
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                stack.pop()
                path.pop()
    return []


def missing_deps(entries):
    """Return a dict mapping ticket id -> list of depends_on ids not present in the board.

    Only tickets that have at least one missing dependency are included.
    Tickets may be added out of order, so this does not block add — it is
    purely informational (used by status rendering and callers who want
    to surface dangling references).
    """
    known_ids = {e["id"] for e in entries}
    result = {}
    for e in entries:
        absent = [d for d in e.get("depends_on", []) if d not in known_ids]
        if absent:
            result[e["id"]] = absent
    return result
