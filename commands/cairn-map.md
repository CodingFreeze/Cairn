---
description: Generate or refresh the repo-warmth map and tooling index.
---

Use the `cairn-map` skill. Ensure `.cairn/` exists (`bin/cairn init`), survey the repo
(prefer Serena symbol tools if the `cairn-adapter` skill reports it present), then append
concise "where things live" bullets and a "Tooling / capability index" line to
`.cairn/vault/map.md` via `bin/cairn vault append map "..."`.

The tooling index must list which tools/skills/MCPs the project uses and WHEN — this is
injected into dispatch prompts later. Do NOT commit — writes touch files only.

$ARGUMENTS
