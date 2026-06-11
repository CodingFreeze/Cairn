import subprocess
import sys
from pathlib import Path

import pytest

CLI = Path(__file__).resolve().parent.parent / "bin" / "cairn"


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=cwd, capture_output=True, text=True,
    )


def _init_dag(tmp_path):
    """init + a 3-ticket DAG: T01; T02 dep T01; T03 dep T02. Add ticket prose."""
    assert _run(["init", "--greenfield"], tmp_path).returncode == 0
    _run(["board", "add", '{"id": "T01"}'], tmp_path)
    _run(["board", "add", '{"id": "T02", "depends_on": ["T01"]}'], tmp_path)
    _run(["board", "add", '{"id": "T03", "depends_on": ["T02"]}'], tmp_path)
    tickets = tmp_path / ".cairn" / "tickets"
    (tickets / "T01.md").write_text("# T01 — Schema layer\n\nDefine the schema.\n")
    (tickets / "T02.md").write_text("# T02 — API\n\nServe the schema.\n")
    return tmp_path


def test_spec_both_writes_mmd_and_html(tmp_path):
    _init_dag(tmp_path)
    r = _run(["spec", "--format", "both"], tmp_path)
    assert r.returncode == 0, r.stderr
    mmd = tmp_path / ".cairn" / "spec" / "graph.mmd"
    html = tmp_path / ".cairn" / "spec" / "graph.html"
    assert mmd.exists() and html.exists()
    for tid in ("T01", "T02", "T03"):
        assert tid in mmd.read_text()
        assert tid in html.read_text()
    # the ticket title heading flows into the graph label
    assert "Schema layer" in mmd.read_text()
    # printed the paths it wrote
    assert "graph.mmd" in r.stdout and "graph.html" in r.stdout


def test_spec_default_is_both(tmp_path):
    _init_dag(tmp_path)
    r = _run(["spec"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / ".cairn" / "spec" / "graph.mmd").exists()
    assert (tmp_path / ".cairn" / "spec" / "graph.html").exists()


def test_spec_format_mermaid_only(tmp_path):
    _init_dag(tmp_path)
    r = _run(["spec", "--format", "mermaid"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / ".cairn" / "spec" / "graph.mmd").exists()
    assert not (tmp_path / ".cairn" / "spec" / "graph.html").exists()


def test_spec_format_html_only(tmp_path):
    _init_dag(tmp_path)
    r = _run(["spec", "--format", "html"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / ".cairn" / "spec" / "graph.html").exists()
    assert not (tmp_path / ".cairn" / "spec" / "graph.mmd").exists()


def test_spec_requires_cairn_dir(tmp_path):
    r = _run(["spec"], tmp_path)
    assert r.returncode != 0
    assert "no .cairn" in (r.stderr + r.stdout).lower()


def test_spec_surfaces_dependency_cycle(tmp_path):
    """A board with a real cycle (T01<->T02) still exits 0 but both graph
    artifacts surface a visible cycle warning. Mutually-dependent ids are valid
    ids, so adding them via the CLI is allowed (only malformed ids are rejected)."""
    assert _run(["init", "--greenfield"], tmp_path).returncode == 0
    assert _run(["board", "add", '{"id": "T01", "depends_on": ["T02"]}'],
                tmp_path).returncode == 0
    assert _run(["board", "add", '{"id": "T02", "depends_on": ["T01"]}'],
                tmp_path).returncode == 0
    r = _run(["spec", "--format", "both"], tmp_path)
    assert r.returncode == 0, r.stderr
    mmd = (tmp_path / ".cairn" / "spec" / "graph.mmd").read_text()
    html = (tmp_path / ".cairn" / "spec" / "graph.html").read_text()
    assert "WARNING: dependency cycle" in mmd
    assert "Dependency cycle detected" in html


def test_spec_surfaces_cycle_through_merged_ticket(tmp_path):
    """A cycle that passes through a MERGED ticket is still drawn in the graph, so
    both artifacts must carry the cycle warning (Fix 2: include_merged=True). T01 is
    merged but T01<->T02 is still a rendered loop."""
    assert _run(["init", "--greenfield"], tmp_path).returncode == 0
    assert _run(["board", "add", '{"id": "T01", "depends_on": ["T02"]}'],
                tmp_path).returncode == 0
    assert _run(["board", "add", '{"id": "T02", "depends_on": ["T01"]}'],
                tmp_path).returncode == 0
    # mark T01 merged so the default (live-only) cycle detection would miss it
    assert _run(["board", "set", "T01", "status=merged"],
                tmp_path).returncode == 0
    r = _run(["spec", "--format", "both"], tmp_path)
    assert r.returncode == 0, r.stderr
    mmd = (tmp_path / ".cairn" / "spec" / "graph.mmd").read_text()
    html = (tmp_path / ".cairn" / "spec" / "graph.html").read_text()
    assert "WARNING: dependency cycle" in mmd
    assert "Dependency cycle detected" in html


def test_spec_refuses_symlinked_spec_dir(tmp_path):
    _init_dag(tmp_path)
    outside = tmp_path / "evil"
    outside.mkdir()
    spec = tmp_path / ".cairn" / "spec"
    if spec.exists():            # init scaffolds a real spec dir; swap for a symlink
        spec.rmdir()
    spec.symlink_to(outside)
    r = _run(["spec", "--format", "both"], tmp_path)
    assert r.returncode != 0
    assert "error" in (r.stderr + r.stdout).lower()
    # nothing written through the symlink to the outside dir
    assert not (outside / "graph.mmd").exists()
