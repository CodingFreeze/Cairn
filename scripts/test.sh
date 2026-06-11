#!/usr/bin/env sh
# Cairn CI runner. Runs the full pytest suite from the plugin root.
# Exits non-zero on ANY test failure so CI (or a pre-commit gate) fails loudly.
set -eu

HERE="$(cd "$(dirname "$0")/.." && pwd)"   # Cairn/ plugin root
cd "$HERE"

echo "==> Cairn test suite (root: $HERE)"
# -q quiet dots; the trailing exit code propagates because of `set -e`.
python3 -m pytest tests -q

echo "==> All tests passed."
