import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import dismiss_filter

import pytest


def _c(text, kind):
    return {"text": text, "kind": kind}


def test_validate_rejects_non_list():
    with pytest.raises(ValueError):
        dismiss_filter.validate_candidates({})


def test_validate_rejects_non_dict_items():
    with pytest.raises(ValueError):
        dismiss_filter.validate_candidates(["x"])


def test_validate_rejects_non_string_fields():
    with pytest.raises(ValueError):
        dismiss_filter.validate_candidates([{"kind": 1, "text": "y"}])


def test_validate_accepts_well_formed():
    cands = [{"kind": "decisions", "text": "we decided to use postgres"}]
    assert dismiss_filter.validate_candidates(cands) == cands


def test_keeps_durable_decision():
    cands = [_c("We decided to use Postgres for the vault index", "decisions")]
    kept = dismiss_filter.filter_candidates(cands)
    assert len(kept) == 1


def test_drops_transient_chatter():
    cands = [_c("ok thanks", "decisions"), _c("let me check that", "decisions")]
    assert dismiss_filter.filter_candidates(cands) == []


def test_drops_too_short():
    cands = [_c("yes", "issues")]
    assert dismiss_filter.filter_candidates(cands) == []


def test_keeps_issue_with_remedy():
    cands = [_c("CI fails on tz; remedy: pin UTC in tests", "issues")]
    kept = dismiss_filter.filter_candidates(cands)
    assert len(kept) == 1


def test_drops_unknown_kind():
    cands = [_c("A perfectly durable looking sentence about architecture", "gossip")]
    assert dismiss_filter.filter_candidates(cands) == []


def test_dedupes_identical_text():
    cands = [
        _c("Auth uses JWT with 15-minute access tokens", "decisions"),
        _c("Auth uses JWT with 15-minute access tokens", "decisions"),
    ]
    assert len(dismiss_filter.filter_candidates(cands)) == 1


def test_is_durable_signal_words():
    assert dismiss_filter.is_durable("We decided to ban global state") is True
    assert dismiss_filter.is_durable("the schema is a users table with id, email") is True
    assert dismiss_filter.is_durable("brb") is False


def test_filter_respects_existing_vault_entries():
    cands = [_c("Auth uses JWT with 15-minute access tokens", "decisions")]
    kept = dismiss_filter.filter_candidates(
        cands, existing={"decisions": "Auth uses JWT with 15-minute access tokens"}
    )
    assert kept == []  # already in vault -> not re-harvested
