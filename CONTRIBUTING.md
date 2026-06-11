# Contributing

## Setup

No dependencies — the core is stdlib-only Python 3.9+.

```bash
git clone https://github.com/CodingFreeze/Cairn
cd ProjectCairn
python3 -m pytest tests/ -q   # full suite, should pass in ~20s
```

## Ground rules

- **Every functional file stays under 300 lines.** `tests/test_structure.py` enforces it —
  split modules rather than fighting it.
- **All `.cairn/` file I/O goes through `bin/cairn_core/safepath.py`** (dir-fd anchored,
  symlink-refusing). Never `open()` a vault/board path directly.
- **Every git-bound value is validated** (`boardcheck.py`, `reconcile._check_ref`) and git
  calls use `--end-of-options`. Keep new code self-defending, not caller-trusting.
- **Tests with the change.** Bug fix = regression test. Feature = behavior tests.
- Conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`).

## Where things live

See `ARCHITECTURE.md` for the module map and `INDEX.md` for the full file inventory.
