---
description: Query the durable vault across sessions.
---

Use the `cairn-recall` skill to answer the user's question from durable memory.

Check for enrichment engines via the `cairn-adapter` skill; if present, query them
semantically, otherwise run `bin/cairn recall "<terms>"` over the flat-file vault. Group
results by file and quote the matching bullets. If nothing matches, say so — never fabricate
memory. This is read-only.

$ARGUMENTS
