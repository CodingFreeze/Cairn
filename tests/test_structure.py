import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # the Cairn/ plugin root
MANIFEST = ROOT / ".claude-plugin" / "plugin.json"

EXPECTED_SKILLS = [
    "cairn-vault", "cairn-map", "cairn-recall",
    "cairn-handoff", "cairn-adapter", "cairn-dismiss",
]
EXPECTED_COMMANDS = ["cairn-plan", "cairn-run", "cairn-resume", "cairn-status"]
EXPECTED_AGENTS = ["cairn-implementer", "cairn-reviewer", "cairn-tester"]


def load_manifest():
    return json.loads(MANIFEST.read_text())


def test_manifest_required_fields():
    m = load_manifest()
    assert m["name"] == "cairn"
    assert isinstance(m["version"], str) and m["version"]
    assert m["description"]
    assert "skills" in m and "commands" in m and "agents" in m and "hooks" in m


def test_manifest_lists_every_skill():
    m = load_manifest()
    listed = {Path(p).parts[-2] for p in m["skills"]}  # skills/<name>/SKILL.md
    assert set(EXPECTED_SKILLS) <= listed, listed


def test_manifest_lists_every_command_and_agent():
    m = load_manifest()
    cmds = {Path(p).stem for p in m["commands"]}
    agents = {Path(p).stem for p in m["agents"]}
    assert set(EXPECTED_COMMANDS) <= cmds, cmds
    assert set(EXPECTED_AGENTS) <= agents, agents


import re

# --- helper: minimal, dependency-free YAML frontmatter parser ---------------
def parse_frontmatter(text):
    """Extract the leading --- ... --- block as a flat dict. Stdlib only."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end].strip("\n")
    data = {}
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, val = line.partition(":")
        if not sep:
            continue
        data[key.strip()] = val.strip().strip('"').strip("'")
    return data


# --- 1. every skill referenced in plugin.json exists on disk ----------------
def test_every_referenced_artifact_exists():
    m = load_manifest()
    refs = list(m["skills"]) + list(m["commands"]) + list(m["agents"])
    refs.append(m["hooks"])
    for rel in refs:
        assert (ROOT / rel).exists(), f"missing artifact: {rel}"


# --- 2. every SKILL.md has valid frontmatter with name + description --------
def test_every_skill_has_valid_frontmatter():
    for skill_md in (ROOT / "skills").glob("cairn-*/SKILL.md"):
        fm = parse_frontmatter(skill_md.read_text())
        assert fm is not None, f"no frontmatter: {skill_md}"
        assert fm.get("name"), f"missing name: {skill_md}"
        assert fm.get("description"), f"missing description: {skill_md}"


# --- 3. no functional file exceeds 300 lines --------------------------------
FUNCTIONAL_GLOBS = ["bin/cairn", "bin/cairn_core/*.py", "tests/*.py", "scripts/*.sh",
                    "evals/continuation/*.py"]


def test_no_functional_file_exceeds_300_lines():
    offenders = []
    for pattern in FUNCTIONAL_GLOBS:
        for f in ROOT.glob(pattern):
            n = len(f.read_text().splitlines())
            if n > 300:
                offenders.append(f"{f.relative_to(ROOT)}: {n} lines")
    assert not offenders, offenders


# --- 4. no secret-looking strings anywhere in the package -------------------
SECRET_PATTERNS = [
    r"ghp_[A-Za-z0-9]{30,}",                  # GitHub PAT (classic)
    r"github_pat_[A-Za-z0-9_]{30,}",          # GitHub PAT (fine-grained)
    r"sk-[A-Za-z0-9]{20,}",                   # OpenAI-style secret key
    r"sk-ant-[A-Za-z0-9\-]{20,}",             # Anthropic key
    r"AKIA[0-9A-Z]{16}",                      # AWS access key id
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",    # PEM private key
    r"xox[baprs]-[A-Za-z0-9-]{10,}",          # Slack token
    r"AIza[0-9A-Za-z_\-]{35}",                # Google API key
]
SCAN_SUFFIXES = {".py", ".md", ".json", ".sh", ".txt", ".jsonl", ".yaml", ".yml"}
SKIP_DIRS = {".git", "__pycache__", "node_modules"}


def test_no_secrets_in_codebase():
    rx = re.compile("|".join(SECRET_PATTERNS))
    hits = []
    for f in ROOT.rglob("*"):
        if not f.is_file() or f.suffix not in SCAN_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in f.parts):
            continue
        if f.name == "test_structure.py":   # this file defines the patterns
            continue
        for i, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
            if rx.search(line):
                hits.append(f"{f.relative_to(ROOT)}:{i}")
    assert not hits, f"secret-looking strings found: {hits}"


import os
import stat


def test_runner_exists_and_is_executable():
    runner = ROOT / "scripts" / "test.sh"
    assert runner.exists(), "scripts/test.sh missing"
    mode = runner.stat().st_mode
    assert mode & stat.S_IXUSR, "scripts/test.sh not executable"
    body = runner.read_text()
    assert body.startswith("#!/"), "missing shebang"
    assert "pytest" in body, "runner does not invoke pytest"
    assert "set -e" in body or "set -eu" in body, "runner must fail-fast"


def test_marketplace_manifest_valid():
    mk = ROOT / ".claude-plugin" / "marketplace.json"
    assert mk.exists(), "marketplace.json missing"
    data = json.loads(mk.read_text())
    assert data.get("name"), "marketplace needs a name"
    plugins = data.get("plugins")
    assert isinstance(plugins, list) and plugins, "marketplace needs plugins[]"
    names = {p.get("name") for p in plugins}
    assert "cairn" in names, names
    # the cairn entry's source must resolve to a dir holding a plugin manifest
    cairn_entry = next(p for p in plugins if p["name"] == "cairn")
    src = cairn_entry.get("source")
    assert src, "cairn plugin entry needs a source"
    src_dir = (ROOT / src).resolve() if src not in (".", "./") else ROOT
    assert (src_dir / ".claude-plugin" / "plugin.json").exists(), src_dir


def test_index_documents_every_artifact():
    idx = (ROOT / "INDEX.md")
    assert idx.exists(), "INDEX.md missing"
    text = idx.read_text()
    for name in EXPECTED_SKILLS + EXPECTED_COMMANDS + EXPECTED_AGENTS:
        assert name in text, f"INDEX.md does not mention {name}"
    # the index must explain WHEN to use things, not just list them
    assert "When to use" in text or "when to use" in text


def test_architecture_covers_core_concepts():
    arch = (ROOT / "ARCHITECTURE.md")
    assert arch.exists(), "ARCHITECTURE.md missing"
    t = arch.read_text().lower()
    required = [
        "memory-first",            # the thesis
        ".cairn",                  # the layout
        "single-writer",           # mechanism 1
        "worktree",                # mechanism 1
        "board.jsonl",             # mechanism 2 (transactional board)
        "rebase-before-turn",      # mechanism 3
        "reconcil",                # the reconciler loop
        "cursor", "codex",         # portability story
    ]
    missing = [k for k in required if k not in t]
    assert not missing, missing


def test_readme_cross_links_docs_and_runner():
    rd = (ROOT / "README.md").read_text()
    assert "INDEX.md" in rd, "README must link INDEX.md"
    assert "ARCHITECTURE.md" in rd, "README must link ARCHITECTURE.md"
    assert "scripts/test.sh" in rd, "README must document the test runner"
    assert "marketplace" in rd.lower(), "README must document install"
