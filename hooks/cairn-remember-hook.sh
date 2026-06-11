#!/usr/bin/env bash
# Cairn UserPromptSubmit hook — inline memory capture (Factory `#remember` parity).
# Reads the hook JSON payload on stdin; if the prompt starts with `#remember <text>`,
# appends <text> as a timestamped vault decisions entry via the guarded Python CLI
# (so safepath symlink/traversal guards apply — no bash file I/O on the vault).
# Non-matching prompts: exit 0 silently, output NOTHING (UserPromptSubmit stdout
# is injected into context). Always exits 0 so it can never block a prompt.
# `set -u` only: -e/-o pipefail would fight the non-blocking `|| true` pattern.
set -u

LOG=/tmp/cairn-hook.log

# Resolve this plugin's bin/cairn relative to the hook file location.
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAIRN_CLI="${HOOK_DIR}/../bin/cairn"

PAYLOAD="$(cat 2>/dev/null || true)"

# Working directory from the hook payload (fallback to PWD).
CWD="$(printf '%s' "$PAYLOAD" | python3 -c '
import json, os, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
print(data.get("cwd") or os.getcwd())
' 2>/dev/null || echo "$PWD")"

# Extract the remembered text. Match rule: prompt (stripped) starts with
# `#remember <text>`. Code-fence heuristic: a prompt that opens with backticks
# is someone quoting code, not issuing the trigger — skip it.
TEXT="$(printf '%s' "$PAYLOAD" | python3 -c '
import json, re, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
prompt = (data.get("prompt") or "")
if prompt.lstrip().startswith("`"):
    sys.exit(0)
m = re.match(r"#remember\s+(.+)", prompt.strip(), re.S)
if not m:
    sys.exit(0)
print(m.group(1).strip())
' 2>/dev/null || true)"

# No match → silent no-op.
if [ -z "$TEXT" ]; then
    exit 0
fi

# Nearest .cairn dir at or above CWD; none → nothing to remember into.
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

# Append via the guarded CLI (vault whitelist + dir-fd safepath apply).
# Errors are logged, never surfaced — the prompt must always go through.
( cd "$CWD" && python3 "$CAIRN_CLI" vault append decisions "$TEXT" ) \
    >>"$LOG" 2>&1 || echo "$(date -u +%FT%TZ) remember-hook: vault append failed (cwd=$CWD)" >>"$LOG"

exit 0
