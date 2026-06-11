"""Scale/perf budget tests: 1k-ticket boards, 10k-bullet vaults.

Budgets are deliberately generous (1-5s) so slow CI never flakes; on a dev
laptop every op below runs in well under 100ms. Marked `scale` so they can be
deselected with `-m "not scale"`, but they are cheap enough to stay in the
default suite.

reconcile is deliberately OUT of scope here: it shells out to git (rev-list /
branch checks) once per ticket, so its runtime is dominated by subprocess and
repo state, not by Cairn's own algorithms — a wall-clock budget on it would
measure git, not us.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import pytest

from cairn_core import board, boarddoctor, resolve, status, vaultcompact, vaultio

pytestmark = pytest.mark.scale

BOARD_N = 1000
N_TODO = 200  # ready tickets for parallel_safe
N_MERGED = BOARD_N - N_TODO
FIXED = "2026-06-10T00:00:00+00:00"
NEWER = "2026-06-11T00:00:00+00:00"


def _timed(budget, fn, *args, **kwargs):
    """Run fn, assert wall time under budget seconds, return its result."""
    t0 = time.perf_counter()
    out = fn(*args, **kwargs)
    dt = time.perf_counter() - t0
    assert dt < budget, f"{fn.__qualname__} took {dt:.3f}s (budget {budget}s)"
    return out


def _tid(i):
    return f"T{i:04d}"


def _entry(tid, st, deps, files=None):
    return {
        "id": tid, "status": st, "branch": None, "pr": None,
        "depends_on": deps, "owner": None, "files_owned": files or [],
        "updated": FIXED,
    }


def _board_entries():
    """1000 entries: 800 merged in a chain+diamond mix, 200 ready todos.

    Merged block: every ticket chains to its predecessor; every 5th also
    depends on i-2 (diamond joins). Todo block: each depends on TWO merged
    tickets, with parents shared across todos (diamonds over the merged
    layer), and owns one unique file so parallel_safe can take all 200.
    """
    entries = []
    for i in range(1, N_MERGED + 1):
        if i == 1:
            deps = []
        elif i % 5 == 0 and i > 2:
            deps = [_tid(i - 1), _tid(i - 2)]  # diamond join
        else:
            deps = [_tid(i - 1)]  # chain
        entries.append(_entry(_tid(i), "merged", deps))
    for j in range(1, N_TODO + 1):
        i = N_MERGED + j
        deps = [_tid((j % N_MERGED) + 1), _tid(((j + 37) % N_MERGED) + 1)]
        entries.append(_entry(_tid(i), "todo", deps, files=[f"src/mod{i}.py"]))
    return entries


@pytest.fixture(scope="module")
def big_board(tmp_path_factory):
    """Write the 1000-entry board ONCE; share dir + in-memory entries."""
    cairn = tmp_path_factory.mktemp("scaleboard") / ".cairn"
    cairn.mkdir()
    entries = _board_entries()
    board.write_board(cairn, entries)
    return cairn, entries


# --- board + resolve + status budgets ---------------------------------------

def test_read_board_1000_under_2s(big_board):
    cairn, _ = big_board
    got = _timed(2.0, board.read_board, cairn)
    assert len(got) == BOARD_N


def test_next_ready_1000_under_1s(big_board):
    _, entries = big_board
    assert _timed(1.0, resolve.next_ready, entries) == _tid(N_MERGED + 1)


def test_ready_all_1000_under_1s(big_board):
    _, entries = big_board
    ready = _timed(1.0, resolve.ready_all, entries)
    assert len(ready) == N_TODO
    assert ready[0] == _tid(N_MERGED + 1)


def test_parallel_safe_200_ready_under_2s(big_board):
    _, entries = big_board
    ready = resolve.ready_all(entries)
    safe = _timed(2.0, resolve.parallel_safe, entries, ready)
    assert safe == ready  # all files disjoint -> every ready ticket taken


def test_status_render_1000_under_2s(big_board):
    _, entries = big_board
    out = _timed(2.0, status.render, entries)
    lines = out.splitlines()
    assert len(lines) == BOARD_N + 1  # header + one row per ticket
    assert lines[1].startswith(_tid(1))
    assert "NOTE:" not in out  # no missing deps, no cycle, nothing stale


# --- find_cycle budgets ------------------------------------------------------

def _chain_nodes(n):
    return [
        {"id": f"N{i:04d}", "status": "todo",
         "depends_on": [] if i == 1 else [f"N{i-1:04d}"]}
        for i in range(1, n + 1)
    ]


def test_find_cycle_acyclic_1000_under_2s():
    entries = _chain_nodes(1000)
    assert _timed(2.0, resolve.find_cycle, entries) == []


def test_find_cycle_planted_10_node_cycle_under_2s():
    entries = _chain_nodes(1000)
    by_id = {e["id"]: e for e in entries}
    # Close N0500..N0509 into a ring: the chain gives i -> i-1; add 500 -> 509.
    by_id["N0500"]["depends_on"].append("N0509")
    cycle = _timed(2.0, resolve.find_cycle, entries)
    assert set(cycle) == {f"N{i:04d}" for i in range(500, 510)}


# --- vault budgets -----------------------------------------------------------

def test_vault_search_after_2000_appends_under_1s(tmp_path):
    cairn = tmp_path / ".cairn"
    for i in range(2000):
        vaultio.append(cairn, "decisions",
                       f"decision {i}: alpha-{i % 7} chose option {i % 13}",
                       now=FIXED)
    hits = _timed(1.0, vaultio.search, cairn, "alpha-3 option", limit=20)
    assert len(hits) == 20
    assert all(name == "decisions" for name, _ in hits)


def test_vaultcompact_plan_10k_under_3s_and_apply_counts(tmp_path):
    cairn = tmp_path / ".cairn"
    vdir = cairn / "vault"
    vdir.mkdir(parents=True)
    unique, dups = 9500, 500
    bullets = [f"- {FIXED} — note {i}" for i in range(unique)]
    bullets += [bullets[0]] * dups  # 500 exact duplicates of the first bullet
    (vdir / "decisions.md").write_text(
        "# Decisions — append-only log\n\n" + "\n".join(bullets) + "\n")

    p = _timed(3.0, vaultcompact.plan, cairn, "decisions", keep=50)
    assert p["total"] == unique + dups
    assert p["duplicates"] == dups
    assert len(p["archived"]) == unique - 50
    assert len(p["kept"]) == 50

    vaultcompact.apply_plan(cairn, p, now=FIXED)
    assert (vdir / "archive" / "decisions-archive.md").exists()
    p2 = vaultcompact.plan(cairn, "decisions", keep=50)
    assert p2["total"] == 50
    assert p2["duplicates"] == 0
    assert p2["archived"] == []
    assert p2["kept"] == p["kept"]  # newest 50 survived the rewrite intact


# --- board doctor budget -----------------------------------------------------

def test_boarddoctor_diagnose_1000_plus_50_dups_under_2s(tmp_path):
    cairn = tmp_path / ".cairn"
    cairn.mkdir()
    entries = _board_entries()
    # Plant 50 duplicate-id lines (newer `updated`, as a team merge would leave).
    planted = [dict(entries[i], updated=NEWER) for i in range(50)]
    board.write_board(cairn, entries + planted)

    diag = _timed(2.0, boarddoctor.diagnose, cairn)
    assert len(diag["keep"]) == BOARD_N
    assert len(diag["dropped"]) == 50
    assert diag["quarantined"] == []
    kept = {e["id"]: e for e in diag["keep"]}
    for d in planted:  # the newest line wins for every duplicated id
        assert kept[d["id"]]["updated"] == NEWER
