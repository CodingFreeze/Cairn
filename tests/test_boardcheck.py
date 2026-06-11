"""Tests for cairn_core.boardcheck — branch/settable validation + read-side checks."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import json  # noqa: E402

import pytest  # noqa: E402

from cairn_core import board, boardcheck  # noqa: E402


# --- validate_branch ---

def test_validate_branch_accepts_ticket_branch():
    boardcheck.validate_branch("cairn/T01")  # must not raise


def test_validate_branch_accepts_main():
    boardcheck.validate_branch("main")  # must not raise


def test_validate_branch_accepts_none():
    boardcheck.validate_branch(None)  # must not raise


def test_validate_branch_rejects_leading_dash():
    with pytest.raises(ValueError):
        boardcheck.validate_branch("--evil")


def test_validate_branch_rejects_dotdot():
    with pytest.raises(ValueError):
        boardcheck.validate_branch("a..b")


def test_validate_branch_rejects_newline():
    with pytest.raises(ValueError):
        boardcheck.validate_branch("a\nb")


def test_validate_branch_rejects_non_str():
    with pytest.raises(ValueError):
        boardcheck.validate_branch(42)


# --- validate_settable: produces/consumes contract-name charset ---

def test_validate_settable_produces_rejects_gt():
    with pytest.raises(ValueError):
        boardcheck.validate_settable({"produces": ["a>b"]})


def test_validate_settable_consumes_rejects_gt():
    with pytest.raises(ValueError):
        boardcheck.validate_settable({"consumes": ["a>b"]})


def test_validate_settable_produces_rejects_newline():
    with pytest.raises(ValueError):
        boardcheck.validate_settable({"produces": ["a\nb"]})


def test_validate_settable_consumes_rejects_newline():
    with pytest.raises(ValueError):
        boardcheck.validate_settable({"consumes": ["a\nb"]})


def test_validate_settable_accepts_clean_contract_names():
    boardcheck.validate_settable(
        {"produces": ["UserSchema"], "consumes": ["OrderSchema"]}
    )  # must not raise


# --- read-side fail-closed: branch validated on every board read ---

def test_read_board_rejects_evil_branch(tmp_path):
    entry = {"id": "T01", "status": "todo", "depends_on": [], "branch": "--evil"}
    (tmp_path / "board.jsonl").write_text(json.dumps(entry) + "\n")
    with pytest.raises(ValueError, match="branch"):
        board.read_board(tmp_path)


def test_validate_branch_rejects_git_forbidden_patterns():
    for bad in ("cairn/T01.lock", "feature.", "cairn/.hidden"):
        with pytest.raises(ValueError, match="git-forbidden"):
            boardcheck.validate_branch(bad)
