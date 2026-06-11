---
name: cairn-status
description: Print the Cairn board — every ticket's id, status, dependencies, and branch — as an aligned table. Read-only snapshot of the control plane.
---

# cairn-status — board snapshot

Run `cairn status` and print the table verbatim. Then add a one-line summary: counts per
status (e.g. "3 merged, 1 in-progress, 2 todo, 1 blocked") and, if any ticket is `blocked`,
name it and point at the relevant `vault/issues.md` entry. Read-only — write nothing.
