"""Relevance filter for cairn-dismiss: keep only durable/reusable facts.

A candidate is {"text": str, "kind": one of VALID_KINDS}. The filter drops transient
chatter, too-short fragments, unknown kinds, duplicates, and anything already in the
vault. Conservative by design — better to skip a borderline fact than pollute the vault.

FALLBACK PATH ONLY: the PRIMARY memory-capture path is the implementer's structured
summary fields (SCHEMA_UPDATES / DECISIONS / ISSUES_FOUND) folded into the vault by
the sole-writer orchestrator in /cairn-run step 5 — no heuristic involved. This
keyword filter exists only for unstructured session-end harvest (the SessionEnd
hook) and interactive `cairn dismiss`, where no structured summary is available.
"""

VALID_KINDS = {"decisions", "issues", "schema", "map"}

MIN_LEN = 15  # characters; shorter than this is almost never a durable fact

# Phrases that mark transient conversation, not durable memory.
TRANSIENT = (
    "ok thanks", "thanks", "let me check", "brb", "one sec", "hold on",
    "got it", "sounds good", "looks good", "yes", "no", "sure", "cool",
)

# Words that signal a durable/reusable fact worth persisting.
DURABLE_SIGNALS = (
    "decided", "decision", "chose", "use ", "uses ", "using", "schema", "contract",
    "remedy", "gotcha", "because", "must", "never", "always", "convention",
    "located", "lives in", "depends on", "api", "endpoint", "table", "ban ",
    "token", "auth", "jwt",
)


def is_durable(text):
    """Heuristic: is this a durable, reusable fact (not chatter)?"""
    t = (text or "").strip().lower()
    if len(t) < MIN_LEN:
        return False
    if any(t == phrase or t.startswith(phrase + " ") for phrase in TRANSIENT):
        return False
    return any(sig in t for sig in DURABLE_SIGNALS)


def validate_candidates(candidates):
    """Validate that `candidates` is a JSON array of {kind, text} string objects.

    Raises ValueError with a clean message otherwise (so the CLI never leaks an
    uncaught AttributeError on `{}` or `["x"]`).
    """
    msg = "dismiss candidates must be a JSON array of {kind,text} objects"
    if not isinstance(candidates, list):
        raise ValueError(msg)
    for c in candidates:
        if not isinstance(c, dict):
            raise ValueError(msg)
        if not isinstance(c.get("kind"), str) or not isinstance(c.get("text"), str):
            raise ValueError(msg)
    return candidates


def filter_candidates(candidates, existing=None):
    """Return the subset of candidates worth writing to the vault.

    `existing` (optional) maps kind -> already-present vault text; matching candidates
    are dropped so dismiss never re-harvests known facts.
    """
    validate_candidates(candidates)
    existing = existing or {}
    kept = []
    seen = set()
    for c in candidates:
        kind = c.get("kind")
        text = (c.get("text") or "").strip()
        if kind not in VALID_KINDS:
            continue
        if not is_durable(text):
            continue
        if text in seen:
            continue
        if text in existing.get(kind, ""):
            continue
        seen.add(text)
        kept.append({"text": text, "kind": kind})
    return kept
