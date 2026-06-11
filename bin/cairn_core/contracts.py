"""Data contracts as checkable artifacts (.cairn/contracts/<name>.schema.json).

Today the board carries contract NAMES only (produces/consumes) and the spec
graph draws producer -> consumer edges; drift between the name and the actual
shape is detected by vibes. This module makes each named contract a JSON Schema
file so drift becomes a deterministic finding:

  - missing_contract  (warn)  a produced name has no contract file yet;
  - orphan_consumer   (error) a consumed name has NO producer on the board;
  - invalid_contract  (error) a contract file is not valid JSON-Schema-ish
                              (or its name is unsafe as a filename);
  - unused_contract   (info)  a contract file no board ticket produces.

SECURITY: contract names become filesystem leaves (<name>.schema.json), so they
are held to the SAME charset rules as ticket ids (boardcheck.ID_RE) plus the
produces/consumes rules (no newline, no '>'). All file I/O goes through the
safepath guards (dir-fd-anchored, symlink-refusing).
"""
import json
import os
from pathlib import Path

from cairn_core import board
from cairn_core.boardcheck import ID_RE
from cairn_core.safepath import atomic_write, safe_mkdir, safe_open_read

# A JSON object is "structurally plausible" as a JSON Schema if it carries at
# least one of these draft-agnostic keywords (stdlib check, NOT full draft
# validation — we gate drift, we don't re-implement a validator).
_SCHEMA_KEYS = ("type", "properties", "$ref", "oneOf", "anyOf", "allOf", "enum")


def validate_contract_name(name):
    """Validate a contract name for use as a .cairn/contracts/ filename leaf.

    Same charset rule as ticket ids / produces-consumes names: alphanumeric
    start, then [A-Za-z0-9._-]; no '/', no '..', no newline, no '>' (the regex
    already excludes them — the explicit rechecks mirror boardcheck's
    belt-and-suspenders style). Raises ValueError on violation.
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError("contract name must be a non-empty string")
    if (not ID_RE.fullmatch(name) or ".." in name or "\n" in name
            or ">" in name or "/" in name):
        raise ValueError(
            "contract name must match [A-Za-z0-9][A-Za-z0-9._-]* and contain "
            f"no '..', '/', '>' or newline (got: {name!r})"
        )


def contract_path(cairn_dir, name):
    """Path of the contract artifact for `name` (validates the name first)."""
    validate_contract_name(name)
    return Path(cairn_dir) / "contracts" / f"{name}.schema.json"


def _check_schema_text(schema_text):
    """Raise ValueError unless `schema_text` is valid JSON AND plausible schema."""
    try:
        doc = json.loads(schema_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"contract is not valid JSON: {e}") from e
    if not isinstance(doc, dict) or not any(k in doc for k in _SCHEMA_KEYS):
        raise ValueError(
            "contract must be a JSON object with at least one of: "
            + "/".join(_SCHEMA_KEYS)
        )


def add(cairn_dir, name, schema_text, allow_update=False):
    """Validate and atomically write `.cairn/contracts/<name>.schema.json`.

    `schema_text` must be (a) valid JSON and (b) structurally plausible JSON
    Schema (see _check_schema_text). Refuses to overwrite an existing contract
    unless `allow_update=True` — a contract is a shared shape; silent
    redefinition is exactly the drift this module exists to catch.
    Returns the written path.
    """
    path = contract_path(cairn_dir, name)
    _check_schema_text(schema_text)
    if not allow_update and os.path.lexists(str(path)):
        raise ValueError(
            f"contract already exists: {name} (pass allow_update=True / "
            "--update to redefine it deliberately)"
        )
    safe_mkdir(cairn_dir, path.parent)
    if not schema_text.endswith("\n"):
        schema_text += "\n"
    atomic_write(cairn_dir, path, schema_text)
    return path


def _finding(kind, severity, name, detail):
    return {"finding": kind, "severity": severity, "name": name, "detail": detail}


def format_finding(f):
    """One-line human rendering: kind[severity] name — detail."""
    return f"{f['finding']}[{f['severity']}] {f['name']} — {f['detail']}"


def _producers(entries):
    """Map contract name -> sorted ticket ids producing it (cancelled excluded)."""
    out = {}
    for e in entries:
        if e.get("status") == "cancelled":
            continue
        for n in e.get("produces") or []:
            out.setdefault(n, []).append(str(e.get("id", "")))
    return {n: sorted(t) for n, t in out.items()}


def _contract_files(cairn_dir):
    """Names of on-disk contracts ({name: leaf_path}). Refuses a symlinked dir."""
    cdir = Path(cairn_dir) / "contracts"
    if os.path.islink(str(cdir)):
        raise ValueError(f"refusing: contracts dir is a symlink: {cdir}")
    if not cdir.is_dir():
        return {}
    out = {}
    for leaf in sorted(os.listdir(str(cdir))):
        if leaf.endswith(".schema.json"):
            out[leaf[: -len(".schema.json")]] = cdir / leaf
    return out


def _check_names(cairn_dir, names, producers, files):
    """Findings for a set of produced/consumed contract names (shared core)."""
    findings = []
    produced, consumed = names
    for n in sorted(produced):
        try:
            validate_contract_name(n)
        except ValueError as e:
            findings.append(_finding("invalid_contract", "error", n, str(e)))
            continue
        if n not in files:
            findings.append(_finding(
                "missing_contract", "warn", n,
                f"produced but has no .cairn/contracts/{n}.schema.json",
            ))
    for n in sorted(consumed):
        if n not in producers:
            findings.append(_finding(
                "orphan_consumer", "error", n,
                "consumed but no board ticket produces it",
            ))
    # Validate the files for every name this scope touches.
    for n in sorted((set(produced) | set(consumed)) & set(files)):
        try:
            with safe_open_read(cairn_dir, files[n]) as fh:
                _check_schema_text(fh.read())
        except ValueError as e:
            findings.append(_finding("invalid_contract", "error", n, str(e)))
    return findings


def check(cairn_dir, entries):
    """Board-wide contract findings (see module docstring for the four kinds)."""
    producers = _producers(entries)
    files = _contract_files(cairn_dir)
    consumed = set()
    for e in entries:
        consumed.update(e.get("consumes") or [])
    findings = _check_names(
        cairn_dir, (set(producers), consumed), producers, files)
    # EVERY contract file must be valid — including files no ticket references
    # yet (the scoped pass above only validated produced/consumed names).
    for n in sorted(set(files) - (set(producers) | consumed)):
        try:
            with safe_open_read(cairn_dir, files[n]) as fh:
                _check_schema_text(fh.read())
        except ValueError as e:
            findings.append(_finding("invalid_contract", "error", n, str(e)))
    for n in sorted(set(files) - set(producers)):
        findings.append(_finding(
            "unused_contract", "info", n, "contract file has no producer ticket"))
    return findings


def check_ticket(cairn_dir, entry, strict=False):
    """`check` scoped to one ticket's produces/consumes (the merge gate).

    Reads the board itself (orphan_consumer needs every ticket's produces).
    With `strict=True` a missing_contract is escalated to severity=error: under
    strict_contracts a produced shape MUST exist as an artifact before merge.
    """
    entries = board.read_board(cairn_dir)
    producers = _producers(entries)
    files = _contract_files(cairn_dir)
    findings = _check_names(
        cairn_dir,
        (set(entry.get("produces") or []), set(entry.get("consumes") or [])),
        producers, files,
    )
    if strict:
        for f in findings:
            if f["finding"] == "missing_contract":
                f["severity"] = "error"
    return findings


def strict_enabled(cairn_dir):
    """True iff .cairn/config.json has "strict_contracts": true.

    Defensive read: a missing, unreadable, corrupt, or non-dict config — or a
    non-true value — all mean non-strict. The gate must never crash a merge
    because an operator hand-edited the config badly.
    """
    cfg_path = Path(cairn_dir) / "config.json"
    try:
        with safe_open_read(cairn_dir, cfg_path) as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return False
    return isinstance(cfg, dict) and cfg.get("strict_contracts") is True
