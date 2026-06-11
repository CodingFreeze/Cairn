"""Thin detect+mirror layer for optional enrichment engines (Serena / claude-mem).

Pure routing logic with dependency-injected presence flags so it is testable without
the real MCP tools. NEVER a hard dependency: if no engine is present, mirror planning
returns no routes and recall planning falls back to grep — silently, no exceptions.
"""

# MCP tool-name prefixes that signal each engine is installed in the session.
SERENA_PREFIX = "mcp__plugin_serena_serena__"
CLAUDE_MEM_PREFIX = "mcp__plugin_claude-mem_"


def detect_engines(tool_names):
    """Given the list of available tool names, report which engines are present."""
    names = list(tool_names or [])
    return {
        "serena": any(n.startswith(SERENA_PREFIX) for n in names),
        "claude_mem": any(n.startswith(CLAUDE_MEM_PREFIX) for n in names),
    }


def plan_mirror(present, name, text):
    """Return mirror-write routes for the engines that are present.

    Each route is a dict the calling skill executes via the engine's MCP tool. Empty
    list => silent flat-file-only fallback.
    """
    routes = []
    if present.get("serena"):
        routes.append({"engine": "serena", "action": "write_memory",
                       "key": f"cairn/{name}", "text": text})
    if present.get("claude_mem"):
        routes.append({"engine": "claude_mem", "action": "memory_add",
                       "category": name, "text": text})
    return routes


def plan_recall(present, query):
    """Decide how to answer a recall query: enrichment engine(s) first, else grep."""
    engines = [k for k in ("claude_mem", "serena") if present.get(k)]
    if engines:
        return {"mode": "engine", "engines": engines, "query": query}
    return {"mode": "grep", "query": query}
