"""Render and merge map.md sections — including the tooling / capability index.

The tooling index is the slice of repo memory injected into per-ticket dispatch prompts,
so the implementer knows which tools/skills/MCPs the project uses and when.
"""
import re

TOOLING_HEADER = "## Tooling / capability index"


def render_tooling_index(entries):
    """Render the tooling-index section from [{name, kind, when}, ...]."""
    lines = [TOOLING_HEADER, ""]
    if not entries:
        lines.append("_(none detected yet — populated by cairn-map)_")
        return "\n".join(lines) + "\n"
    for e in entries:
        lines.append(f"- **{e['name']}** ({e['kind']}) — {e['when']}")
    return "\n".join(lines) + "\n"


def extract_tooling_entries(rendered):
    """Parse a rendered tooling-index section back into entries (roundtrip helper)."""
    entries = []
    pat = re.compile(r"^- \*\*(?P<name>.+?)\*\* \((?P<kind>.+?)\) — (?P<when>.+)$")
    for line in rendered.splitlines():
        m = pat.match(line.strip())
        if m:
            entries.append({"name": m.group("name"), "kind": m.group("kind"),
                            "when": m.group("when")})
    return entries


def upsert_section(existing, header, new_block):
    """Replace the `header` section of `existing` with `new_block`; append if absent.

    A section runs from its `## ` header to the next `## ` header (or EOF).
    """
    lines = existing.splitlines(keepends=True)
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == header:
            start = i
            break
    if start is None:
        sep = "" if existing.endswith("\n") else "\n"
        return existing + sep + "\n" + new_block
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    block = new_block if new_block.endswith("\n") else new_block + "\n"
    return "".join(lines[:start]) + block + "".join(lines[end:])
