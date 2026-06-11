import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parent.parent / "bin" / "cairn"


def run(args, cwd):
    r = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=cwd, capture_output=True, text=True,
    )
    assert r.returncode == 0, f"`cairn {' '.join(args)}` failed: {r.stderr}"
    return r.stdout.strip()


def test_full_board_lifecycle_reaches_all_merged(tmp_path):
    # 1. init a fresh project in a throwaway temp dir
    run(["init", "--greenfield"], tmp_path)
    cairn = tmp_path / ".cairn"
    assert (cairn / "board.jsonl").exists()

    # 2. hand-author a tiny 2-3 ticket DAG: T01, T02->T01, T03->T02
    run(["board", "add", '{"id": "T01"}'], tmp_path)
    run(["board", "add", '{"id": "T02", "depends_on": ["T01"]}'], tmp_path)
    run(["board", "add", '{"id": "T03", "depends_on": ["T02"]}'], tmp_path)

    # 3. simulate the reconciler loop: next -> set merged, until empty
    expected_order = ["T01", "T02", "T03"]
    seen = []
    for _ in range(10):  # bounded; should take exactly 3 iterations
        nxt = run(["next"], tmp_path)
        if nxt == "":
            break
        seen.append(nxt)
        run(["board", "set", nxt, "status=merged"], tmp_path)

    # 4. assert the loop drained the DAG in dependency order
    assert seen == expected_order, seen
    assert run(["next"], tmp_path) == ""        # nothing left ready

    # 5. assert ALL tickets reached merged
    import json
    listing = json.loads(run(["board", "list"], tmp_path))
    assert {e["id"]: e["status"] for e in listing} == {
        "T01": "merged", "T02": "merged", "T03": "merged",
    }


def test_dependency_gate_blocks_until_parent_merged(tmp_path):
    run(["init", "--greenfield"], tmp_path)
    run(["board", "add", '{"id": "T01"}'], tmp_path)
    run(["board", "add", '{"id": "T02", "depends_on": ["T01"]}'], tmp_path)
    # T02 must NOT be offered while T01 is unmerged
    assert run(["next"], tmp_path) == "T01"
    run(["board", "set", "T01", "status=in-progress"], tmp_path)
    assert run(["next"], tmp_path) == ""        # T01 not merged -> nothing ready


def test_vault_files_exist_and_are_appendable(tmp_path):
    run(["init", "--greenfield"], tmp_path)
    vault = tmp_path / ".cairn" / "vault"
    for name in ["schema.md", "decisions.md", "issues.md", "map.md"]:
        f = vault / name
        assert f.exists(), f"missing vault file: {name}"
        before = f.read_text()
        with f.open("a") as fh:                 # single-writer append, never clobber
            fh.write("\n- e2e dogfood appended entry\n")
        assert f.read_text().startswith(before)
        assert "e2e dogfood appended entry" in f.read_text()

    # handoff dir exists and is writable (portable resume pack target)
    handoff = tmp_path / ".cairn" / "handoff"
    assert handoff.is_dir()
    (handoff / "latest.md").write_text("# resume pack\n")
    assert (handoff / "latest.md").exists()
