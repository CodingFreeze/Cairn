---
description: Harvest durable conversational facts into the .cairn vault.
---

Use the `cairn-dismiss` skill to capture durable, reusable facts from THIS conversation
before the session ends.

Gather candidates as `{"kind","text"}` (kind is one of decisions|issues|schema|map). Since this is an
explicit invocation (human present), show the proposed capture summary FIRST, then on
confirmation run:

`bin/cairn dismiss '[{"kind":"...","text":"..."}, ...]'`

The CLI applies the relevance filter, appends only durable/new facts (single-writer,
append-only), and refreshes the handoff pack. Mirror via `cairn-adapter` if an engine is
present. Do NOT commit — writes touch files only. If the global "dismissed" protocol is also
running, this is just its project-memory step — compose, don't collide.

$ARGUMENTS
