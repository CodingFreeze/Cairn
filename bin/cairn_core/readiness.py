"""Deterministic repo agent-readiness scorer (Factory '/readiness-report' parity).

Pure-stdlib checks for the infrastructure an autonomous coding agent needs to
work safely in a repository: tests, CI, lint config, agent rules, vault notes,
.gitignore, README, and a project manifest. No network, no subprocesses.
"""
import os

_SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__"}


def _walk(repo_path):
    """os.walk that prunes vendored/cache directories in-place."""
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        yield root, dirs, files


def _read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _tests_present(repo):
    for root, dirs, files in _walk(repo):
        if "tests" in dirs:
            return True, "found tests/ directory"
        for f in files:
            if f.endswith(".py") and (f.startswith("test_") or f.endswith("_test.py")):
                return True, "found test file %s" % f
    return False, "no tests/ directory or test_*.py / *_test.py files"


def _ci_config(repo):
    wf = os.path.join(repo, ".github", "workflows")
    if os.path.isdir(wf):
        for f in os.listdir(wf):
            if f.endswith((".yml", ".yaml")):
                return True, "found .github/workflows/%s" % f
    for name in (".gitlab-ci.yml", "Jenkinsfile"):
        if os.path.isfile(os.path.join(repo, name)):
            return True, "found %s" % name
    return False, "no GitHub Actions workflow, .gitlab-ci.yml, or Jenkinsfile"


def _lint_config(repo):
    simple = (
        ".flake8", ".pylintrc", "ruff.toml", ".ruff.toml", "biome.json",
        ".eslintrc", ".eslintrc.json", ".eslintrc.js", ".eslintrc.cjs",
        ".eslintrc.yml", ".eslintrc.yaml", "eslint.config.js",
        "eslint.config.mjs", "eslint.config.cjs",
    )
    for name in simple:
        if os.path.isfile(os.path.join(repo, name)):
            return True, "found %s" % name
    pyproject = _read(os.path.join(repo, "pyproject.toml"))
    for tool in ("[tool.ruff", "[tool.flake8", "[tool.pylint"):
        if tool in pyproject:
            return True, "found %s] in pyproject.toml" % tool
    setup_cfg = _read(os.path.join(repo, "setup.cfg"))
    for section in ("[flake8]", "[pylint", "[ruff"):
        if section in setup_cfg:
            return True, "found %s in setup.cfg" % section
    return False, "no ruff/flake8/pylint/eslint/biome configuration"


def _agent_rules(repo):
    for name in ("AGENTS.md", "CLAUDE.md"):
        if os.path.isfile(os.path.join(repo, name)):
            return True, "found %s" % name
    rules = os.path.join(repo, ".cairn", "rules")
    if os.path.isdir(rules) and os.listdir(rules):
        return True, "found non-empty .cairn/rules/"
    return False, "no AGENTS.md, CLAUDE.md, or non-empty .cairn/rules/"


def _cairn_vault(repo):
    vault = os.path.join(repo, ".cairn", "vault")
    if os.path.isdir(vault):
        for root, _dirs, files in os.walk(vault):
            for f in files:
                path = os.path.join(root, f)
                if f.endswith(".md") and os.path.getsize(path) > 0:
                    return True, "found %s" % os.path.relpath(path, repo)
    return False, "no .cairn/vault/ with at least one non-empty .md"


def _gitignore_present(repo):
    if os.path.isfile(os.path.join(repo, ".gitignore")):
        return True, "found .gitignore"
    return False, "no .gitignore at repo root"


def _readme_present(repo):
    try:
        entries = os.listdir(repo)
    except OSError:
        entries = []
    for f in entries:
        if f.lower() == "readme.md":
            return True, "found %s" % f
    return False, "no README.md at repo root"


def _typed_config(repo):
    for name in ("pyproject.toml", "package.json", "go.mod", "Cargo.toml"):
        if os.path.isfile(os.path.join(repo, name)):
            return True, "found %s" % name
    return False, "no pyproject.toml, package.json, go.mod, or Cargo.toml"


_CHECKS = [
    ("tests_present", _tests_present,
     "add a tests/ directory with test_*.py files"),
    ("ci_config", _ci_config,
     "add a CI workflow under .github/workflows/"),
    ("lint_config", _lint_config,
     "add a lint config (e.g. [tool.ruff] in pyproject.toml)"),
    ("agent_rules", _agent_rules,
     "add an AGENTS.md or CLAUDE.md with agent guidance"),
    ("cairn_vault", _cairn_vault,
     "run cairn init to create .cairn/vault/ with project notes"),
    ("gitignore_present", _gitignore_present,
     "add a .gitignore at the repo root"),
    ("readme_present", _readme_present,
     "add a README.md describing the project"),
    ("typed_config", _typed_config,
     "add a project manifest (pyproject.toml, package.json, ...)"),
]


def report(repo_path):
    """Score a repository's readiness for autonomous agent work.

    Returns {"score": int 0-100, "checks": [{"check", "ok", "detail", "fix"}],
    "summary": str}. Deterministic: same tree in, same dict out.
    """
    repo = os.path.realpath(repo_path)
    checks = []
    for name, fn, fix in _CHECKS:
        ok, detail = fn(repo)
        checks.append({"check": name, "ok": ok, "detail": detail, "fix": fix})
    ok_count = sum(1 for c in checks if c["ok"])
    score = round(100 * ok_count / len(checks))
    failing = [c["check"] for c in checks if not c["ok"]]
    if failing:
        summary = "Readiness %d/100 (%d/%d checks passing). Failing: %s" % (
            score, ok_count, len(checks), ", ".join(failing))
    else:
        summary = "Readiness %d/100 (%d/%d checks passing)." % (
            score, ok_count, len(checks))
    return {"score": score, "checks": checks, "summary": summary}
