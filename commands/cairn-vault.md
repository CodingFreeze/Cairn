---
description: Initialize or append to the durable .cairn vault.
---

Use the `cairn-vault` skill to manage durable project memory.

If the user named a fact to remember, classify it (decision / issue / schema / repo fact),
ensure the vault exists with `bin/cairn init`, then append it with
`bin/cairn vault append <decisions|issues|schema|map> "<fact>"`.

If the user just asked to "set up memory", run `bin/cairn init` and confirm the `.cairn/`
tree was created. Do NOT commit anything — writes touch files only; commit needs operator
permission.

$ARGUMENTS
