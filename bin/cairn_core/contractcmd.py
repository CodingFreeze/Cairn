"""`cairn contract` subcommand (parser + handlers; out of bin/cairn for the
300-line cap, same relocation pattern as dismisscmd).

  cairn contract add <name> [--file PATH | --stdin] [--update]
  cairn contract check [TID]            # JSON findings on stdout
"""
import json
import sys
from pathlib import Path

from cairn_core import board, contracts


def _read_schema_text(args):
    """Schema text from --file or --stdin (the parser enforces exactly one)."""
    if args.stdin:
        return sys.stdin.read()
    # Operator-supplied source path (like a `cairn board add` payload) — it may
    # legitimately live anywhere in the repo, so no .cairn safepath anchoring;
    # the WRITE side (contracts.add) is fully safepath-guarded.
    return Path(args.file).read_text(encoding="utf-8")


def cmd_contract(args, require_dir):
    d = require_dir()
    if args.action == "add":
        path = contracts.add(
            d, args.name, _read_schema_text(args), allow_update=args.update
        )
        print(f"Wrote {path}")
    elif args.action == "check":
        if args.tid:
            entry = board.get_entry(d, args.tid)
            if entry is None:
                sys.exit(f"error: no such ticket: {args.tid}")
            findings = contracts.check_ticket(d, entry)
        else:
            findings = contracts.check(d, board.read_board(d))
        print(json.dumps(findings))
        # Error findings exit non-zero so CI / the run loop can gate on them;
        # warn/info stay exit 0 (advisory, mirrors the non-strict merge gate).
        if any(f["severity"] == "error" for f in findings):
            sys.exit(1)


def register(sub, require_dir):
    """Attach the `contract` subparser to the CLI's subparsers object."""
    pc = sub.add_parser("contract")
    csub = pc.add_subparsers(dest="action", required=True)
    ca = csub.add_parser("add")
    ca.add_argument("name")
    src = ca.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", default=None)
    src.add_argument("--stdin", action="store_true")
    ca.add_argument("--update", action="store_true",
                    help="allow redefining an existing contract")
    cc = csub.add_parser("check")
    cc.add_argument("tid", nargs="?", default=None)
    pc.set_defaults(func=lambda args: cmd_contract(args, require_dir))
