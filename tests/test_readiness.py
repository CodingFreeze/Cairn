import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import readiness


def _repo(tmp_path):
    # macOS /tmp is a symlink; realpath keeps fixtures safepath-friendly.
    return os.path.realpath(tmp_path)


def _write(repo, rel, content="x\n"):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _check(result, name):
    return next(c for c in result["checks"] if c["check"] == name)


def test_empty_repo_scores_zero(tmp_path):
    result = readiness.report(_repo(tmp_path))
    assert result["score"] == 0
    assert len(result["checks"]) == 8
    assert all(not c["ok"] for c in result["checks"])
    for c in result["checks"]:
        assert c["detail"] and c["fix"]


def test_tests_present_via_tests_dir(tmp_path):
    repo = _repo(tmp_path)
    os.makedirs(os.path.join(repo, "tests"))
    assert _check(readiness.report(repo), "tests_present")["ok"]


def test_tests_present_via_test_file_anywhere(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "pkg/sub/test_thing.py")
    assert _check(readiness.report(repo), "tests_present")["ok"]


def test_tests_present_via_suffix_test_file(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "pkg/thing_test.py")
    assert _check(readiness.report(repo), "tests_present")["ok"]


def test_tests_in_skipped_dirs_ignored(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "node_modules/dep/test_x.py")
    _write(repo, ".venv/lib/test_y.py")
    _write(repo, "__pycache__/test_z.py")
    assert not _check(readiness.report(repo), "tests_present")["ok"]


def test_ci_config_github_workflow(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, ".github/workflows/ci.yml", "on: push\n")
    assert _check(readiness.report(repo), "ci_config")["ok"]


def test_ci_config_gitlab(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, ".gitlab-ci.yml")
    assert _check(readiness.report(repo), "ci_config")["ok"]


def test_ci_config_jenkinsfile(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "Jenkinsfile")
    assert _check(readiness.report(repo), "ci_config")["ok"]


def test_lint_config_pyproject_ruff(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "pyproject.toml", "[tool.ruff]\nline-length = 100\n")
    assert _check(readiness.report(repo), "lint_config")["ok"]


def test_lint_config_flake8_file(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, ".flake8", "[flake8]\n")
    assert _check(readiness.report(repo), "lint_config")["ok"]


def test_lint_config_setup_cfg(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "setup.cfg", "[flake8]\nmax-line-length = 100\n")
    assert _check(readiness.report(repo), "lint_config")["ok"]


def test_lint_config_biome(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "biome.json", "{}\n")
    assert _check(readiness.report(repo), "lint_config")["ok"]


def test_lint_config_eslint(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, ".eslintrc.json", "{}\n")
    assert _check(readiness.report(repo), "lint_config")["ok"]


def test_pyproject_without_lint_section_fails_lint(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "pyproject.toml", "[project]\nname = 'x'\n")
    result = readiness.report(repo)
    assert not _check(result, "lint_config")["ok"]
    assert _check(result, "typed_config")["ok"]  # manifest still counts


def test_agent_rules_claude_md(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "CLAUDE.md", "# rules\n")
    assert _check(readiness.report(repo), "agent_rules")["ok"]


def test_agent_rules_agents_md(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "AGENTS.md", "# rules\n")
    assert _check(readiness.report(repo), "agent_rules")["ok"]


def test_agent_rules_cairn_rules_dir(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, ".cairn/rules/style.md", "rule\n")
    assert _check(readiness.report(repo), "agent_rules")["ok"]


def test_agent_rules_empty_rules_dir_fails(tmp_path):
    repo = _repo(tmp_path)
    os.makedirs(os.path.join(repo, ".cairn", "rules"))
    assert not _check(readiness.report(repo), "agent_rules")["ok"]


def test_cairn_vault_needs_nonempty_md(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, ".cairn/vault/notes.md", "")  # empty md does not count
    assert not _check(readiness.report(repo), "cairn_vault")["ok"]
    _write(repo, ".cairn/vault/notes.md", "# note\n")
    assert _check(readiness.report(repo), "cairn_vault")["ok"]


def test_gitignore_present(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, ".gitignore", "*.pyc\n")
    assert _check(readiness.report(repo), "gitignore_present")["ok"]


def test_readme_any_case(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "readme.MD", "# hi\n")
    assert _check(readiness.report(repo), "readme_present")["ok"]


def test_typed_config_package_json(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "package.json", "{}\n")
    assert _check(readiness.report(repo), "typed_config")["ok"]


def test_score_math_partial(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, ".gitignore")
    _write(repo, "README.md", "# x\n")
    result = readiness.report(repo)
    assert result["score"] == 25  # round(100 * 2 / 8)
    assert sum(c["ok"] for c in result["checks"]) == 2


def test_full_repo_scores_100(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "tests/test_a.py", "def test_a(): pass\n")
    _write(repo, ".github/workflows/ci.yml", "on: push\n")
    _write(repo, "pyproject.toml", "[project]\nname='x'\n[tool.ruff]\n")
    _write(repo, "CLAUDE.md", "# rules\n")
    _write(repo, ".cairn/vault/notes.md", "# note\n")
    _write(repo, ".gitignore", "*.pyc\n")
    _write(repo, "README.md", "# x\n")
    result = readiness.report(repo)
    assert result["score"] == 100
    assert all(c["ok"] for c in result["checks"])
    assert "Failing" not in result["summary"]
    assert "100/100" in result["summary"]


def test_summary_mentions_failing_checks(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "README.md", "# x\n")
    result = readiness.report(repo)
    for name in ("tests_present", "ci_config", "lint_config", "agent_rules",
                 "cairn_vault", "gitignore_present", "typed_config"):
        assert name in result["summary"]
    assert "readme_present" not in result["summary"]


def test_report_is_deterministic(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "README.md", "# x\n")
    _write(repo, ".gitignore", "*.pyc\n")
    assert readiness.report(repo) == readiness.report(repo)
