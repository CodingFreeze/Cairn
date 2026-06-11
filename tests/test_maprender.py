import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import maprender


def test_render_tooling_index_lists_tools():
    out = maprender.render_tooling_index([
        {"name": "semgrep", "kind": "MCP", "when": "security gate on PRs"},
        {"name": "pytest", "kind": "tool", "when": "run tests"},
    ])
    assert "## Tooling / capability index" in out
    assert "semgrep" in out and "security gate on PRs" in out
    assert "pytest" in out and "run tests" in out


def test_render_tooling_index_empty():
    out = maprender.render_tooling_index([])
    assert "## Tooling / capability index" in out
    assert "_(none detected" in out


def test_upsert_section_replaces_only_that_section():
    existing = (
        "# Repo map\n\n"
        "## Where things live\n- src/app.py: entry\n\n"
        "## Tooling / capability index\n_(none detected yet)_\n"
    )
    new_tooling = maprender.render_tooling_index([
        {"name": "ruff", "kind": "tool", "when": "lint"},
    ])
    out = maprender.upsert_section(existing, "## Tooling / capability index", new_tooling)
    assert "src/app.py: entry" in out  # other section untouched
    assert "ruff" in out
    assert out.count("## Tooling / capability index") == 1  # no duplicate section


def test_upsert_section_appends_when_absent():
    existing = "# Repo map\n\n## Where things live\n- src/app.py\n"
    out = maprender.upsert_section(existing, "## Notes", "## Notes\nhello\n")
    assert "## Notes" in out and "hello" in out
    assert "src/app.py" in out


def test_extract_tooling_entries_roundtrip():
    rendered = maprender.render_tooling_index([
        {"name": "semgrep", "kind": "MCP", "when": "security gate"},
    ])
    entries = maprender.extract_tooling_entries(rendered)
    assert entries == [{"name": "semgrep", "kind": "MCP", "when": "security gate"}]
