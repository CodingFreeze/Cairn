import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import adapter


def test_detect_none_when_no_tools():
    present = adapter.detect_engines(tool_names=[])
    assert present == {"serena": False, "claude_mem": False}


def test_detect_serena_by_prefix():
    present = adapter.detect_engines(tool_names=["mcp__plugin_serena_serena__find_symbol"])
    assert present["serena"] is True
    assert present["claude_mem"] is False


def test_detect_claude_mem_by_prefix():
    present = adapter.detect_engines(tool_names=["mcp__plugin_claude-mem_mcp-search__search"])
    assert present["claude_mem"] is True


def test_plan_mirror_routes_to_present_engines():
    present = {"serena": True, "claude_mem": False}
    routes = adapter.plan_mirror(present, name="decisions", text="chose flat-file")
    targets = {r["engine"] for r in routes}
    assert targets == {"serena"}  # only the present engine is targeted


def test_plan_mirror_empty_when_none_present():
    routes = adapter.plan_mirror({"serena": False, "claude_mem": False}, "decisions", "x")
    assert routes == []  # silent flat-file fallback — no error, no routes


def test_plan_recall_route_prefers_engine_when_present():
    route = adapter.plan_recall({"serena": True, "claude_mem": True}, "what about auth?")
    assert route["mode"] == "engine"
    assert "claude_mem" in route["engines"] and "serena" in route["engines"]


def test_plan_recall_route_falls_back_to_grep():
    route = adapter.plan_recall({"serena": False, "claude_mem": False}, "what about auth?")
    assert route["mode"] == "grep"  # never errors — flat-file fallback


def test_adapter_is_never_hard_dependency():
    # detection + planning must work with zero tools and zero exceptions
    present = adapter.detect_engines(tool_names=[])
    assert adapter.plan_mirror(present, "issues", "x") == []
    assert adapter.plan_recall(present, "x")["mode"] == "grep"
