#!/usr/bin/env bash
# Cairn SessionEnd hook — deterministic memory harvest.
# Reads the hook JSON payload on stdin, locates the project's .cairn dir, and runs a
# silent dismiss + handoff refresh. NEVER commits or pushes. Always exits 0 so it can
# never block session teardown.
set -u

# Resolve this plugin's bin/cairn relative to the hook file location.
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAIRN_CLI="${HOOK_DIR}/../bin/cairn"

# Determine the working directory from the hook payload (fallback to PWD).
PAYLOAD="$(cat 2>/dev/null || true)"
CWD="$(printf '%s' "$PAYLOAD" | CAIRN_CLI="$CAIRN_CLI" python3 -c '
import json, os, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
print(data.get("cwd") or os.getcwd())
' 2>/dev/null || echo "$PWD")"

# Find the nearest .cairn dir at or above CWD; if none, exit quietly (nothing to harvest).
if ! python3 - "$CWD" <<'PY' 2>/dev/null
import sys
from pathlib import Path
start = Path(sys.argv[1]).resolve()
for cand in [start, *start.parents]:
    if (cand / ".cairn").is_dir():
        sys.exit(0)
sys.exit(1)
PY
then
    exit 0
fi

# The hook has no model in the loop, so it cannot mine the conversation for candidates.
# It does the deterministic, always-safe action: refresh the portable handoff pack so the
# latest board/vault state is captured. (Model-driven candidate harvest runs via the
# `dismissed` keyword / --cairn-dismissed flag path inside an active session.)
( cd "$CWD" && python3 "$CAIRN_CLI" handoff >/dev/null 2>&1 ) || true

# If a candidate file was staged by an active session at .cairn/handoff/dismiss-candidates.json,
# harvest it deterministically and then remove it.
# All candidate file I/O (read + delete) is delegated to the guarded Python CLI so
# safepath guards apply: a symlinked handoff parent dir OR symlinked leaf both cause
# the CLI to refuse with an error and exit non-zero, which the `|| true` absorbs.
# No bash cat/rm on candidate files — the CLI owns the entire I/O path.
( cd "$CWD" && python3 "$CAIRN_CLI" harvest-candidates >/dev/null 2>&1 ) || true

exit 0
