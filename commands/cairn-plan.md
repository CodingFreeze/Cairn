---
name: cairn-plan
description: Decompose a project (greenfield or existing) into a dependency-ordered ticket DAG. Writes tickets/T##.md prose specs and board.jsonl entries via the cairn CLI, and seeds vault/schema.md and vault/map.md. Ends at a fused edit-or-approve gate that also locks the run policy (autonomy) into .cairn/config.json and persists the approved spec as a dated .cairn/specs/ artifact. This is where cross-ticket insight is designed in.
argument-hint: "[--greenfield|--existing] <one-line goal of the project>"
---

# cairn-plan — design the ticket DAG

You are the **planning brain**. You hold the WHOLE project in one context exactly once, so
this is where cross-ticket insight is created (e.g. "define the schema in T03 so T05 consumes
it"). You are the orchestrator here — you ARE allowed to write `.cairn/`.

## 0. Locate / init `.cairn`
> **Invocation:** if `cairn` is not on `PATH` (common when the plugin is freshly installed), call
> the CLI by absolute path: `python3 <plugin-dir>/bin/cairn <args>`. Everywhere this doc
> writes `cairn …`, use that fallback form if the bare command is not found.

Parse `$ARGUMENTS` into two parts — an optional mode flag (`--greenfield` / `--existing`) and
the **one-line goal** (everything else). Then init, passing the goal as a NAMED flag — never as
the positional `path` (the positional is the directory; a goal there creates a dir literally
named after the goal):

```bash
# Example shape — substitute the parsed values; default path is the cwd ".".
cairn init . --goal "Python CLI tip calculator"        # add --greenfield/--existing if given
```

`cairn init --goal` seeds `vault/goal.md`. **You (cairn-plan) own that file from here on**: treat
it as the canonical goal statement and rewrite it as the spec sharpens (scope, non-goals, the
locked architecture decisions). Confirm the printed mode matches reality before proceeding.

## 1. Understand the project
- **existing** mode: build repo warmth first — invoke `cairn-map` (Plan 2) to populate
  `vault/map.md` (symbol map, where-things-live, gotchas, tooling/capability index). Respect
  existing patterns; do not propose rewrites unless asked.
- **greenfield** mode: there is no code yet — derive structure from the user's goal.

## 1b. Foundational architecture gate (lock hard-to-reverse choices FIRST)
Before contracts or tickets, lock the **hard-to-reverse** choices that change ticket *internals* —
the ones expensive to undo after code exists. Surface them as an explicit **AskUserQuestion** (one
question per axis), then lock the answers. Typical axes:
- **Language / runtime** (e.g. Python 3.11 vs Node vs Go) — gates every ticket's idioms + tooling.
- **Storage / persistence** (none · flat file · SQLite · Postgres · external API) — gates the schema.
- **Framework / UI style** (CLI · library · web app + which stack) — gates structure and seams.
- Anything else genuinely load-bearing and costly to reverse (auth model, deploy target).

Rules:
- **Only ask what the goal leaves open.** If the goal already pins an axis (e.g. "Python **CLI** tip
  calculator" fixes language + UI style), confirm it in one line — do NOT re-ask a settled choice.
- **Lock the answers** into `vault/decisions.md` (append; these are durable, contract-shaping
  decisions) and sharpen `vault/goal.md` to reflect the locked architecture.
- Factory locks these THEN decomposes; Cairn must too — jumping straight to tickets bakes in
  reversibility debt. Do this before step 2.

## 2. Design the data contracts FIRST
Before tickets, decide the shared shapes (API types, DB schema, event payloads). Write them to
`vault/schema.md`. This is the carrier that makes later tickets consume earlier ones. The locked
storage/runtime choices from step 1b constrain these shapes — honor them.

## 3. Decompose into a DAG
Produce an ordered set of tickets `T01..T##`. For each ticket decide:
- **goal** (one sentence) and **acceptance criteria** (testable bullets);
- **depends_on** (lower-id tickets that MUST be merged first) — keep the graph shallow and
  parallel-ready;
- **files_owned** (paths this ticket is the writer of — the parallel-ready seam);
- which `vault/schema.md` contracts it produces vs consumes.

Cross-ticket rule: if two tickets need the same shape, ONE ticket defines it (lower id) and the
other depends on it. Never duplicate a contract.

## 4. Write the artifacts (you are the sole writer)
For each ticket, write `tickets/T##.md`:

```markdown
# T## — <title>
## Goal
<one sentence>
## Acceptance criteria
- [ ] <testable>
## Depends on
- T0x (reason)
## Files owned
- path/...
## Produces (schema)
- <contract name> -> vault/schema.md
## Consumes (schema)
- <contract name>
## Notes
<gotchas, tooling to use from vault/map.md>
```

Then register it on the board (the machine-readable control plane). Carry the
data-contract model so the spec graph can render it: set `schema: true` on every
ticket that DEFINES a contract, list the contract names it `produces`, and list
the contracts it `consumes`. The graph draws a schema-dependency edge from each
producer to each consumer and highlights the longest schema chain (the
lock-first critical path):

```bash
cairn board add '{"id":"T##","depends_on":["T0x"],"files_owned":["path/..."],
  "schema":true,"produces":["ContractName"],"consumes":["EarlierContract"]}'
```

(Status defaults to `todo`. Do NOT set a branch — `cairn-run` creates it.
`schema`/`produces`/`consumes` are optional — omit them on non-contract tickets.
One contract is defined by exactly ONE producer; consumers reference it by name.)

**Contracts are artifacts, not just names.** For every `[SCHEMA]` ticket, also write the
contract's JSON Schema skeleton NOW via `cairn contract add` — it lands in
`.cairn/contracts/<name>.schema.json`, and `cairn contract check` (plus the merge gate) verifies
producers/consumers against it instead of detecting drift by vibes. A skeleton with the agreed
field names and types is enough; the producer ticket refines it (`--update`) as it implements:

```bash
cairn contract add ContractName --stdin <<'EOF'
{"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}
EOF
```

**Optional rules scaffold.** If the plan surfaces durable, every-ticket coding rules (style,
security posture, framework idioms beyond what `vault/schema.md` carries), scaffold them now as
`.cairn/rules/*.md` — `/cairn-run` injects these files plus any repo `AGENTS.md` verbatim into
every implementer dispatch via the template's `{{RULES}}` block.

## 5. Spec graph + approval gate (Spec mode)
The board and tickets now exist — turn them into a reviewable **spec** before any run. This is
Cairn's git-native answer to spec-planning: a visual graph the operator edits-or-approves.

1. **Generate the spec graph** from the board + ticket prose:
   ```bash
   cairn spec --format both
   ```
   This writes `.cairn/spec/graph.mmd` (Mermaid) and `.cairn/spec/graph.html` (a self-contained,
   offline, interactive DAG with pan/zoom and a click-to-open spec drawer — no network, no build).

2. **Author the narrative spec.** Write `.cairn/spec/SPEC.md` (you author this prose): the system
   flow — what unlocks what, where the schema flows from producer to consumer tickets, and the key
   design decisions and trade-offs. This is the human-readable companion to the graph.

3. **Narrate the build order + the riskiest coupling.** You hold the whole DAG — state it, don't
   make the operator infer it from the graph:
   - **Topological build order** — the dependency-respecting sequence tickets will merge in (the
     same order `cairn-run` drains via `cairn next`), e.g. `T01 → T02 → T03`. Call out which
     tickets are parallel-ready (no path between them).
   - **Highest-risk schema coupling** — name the deepest producer→consumer fan-out (the contract
     whose change ripples through the most downstream tickets, i.e. the longest schema chain the
     graph highlights). Tell the operator to review THAT contract first — it is the costliest to
     get wrong. (Factory lists this in prose; Cairn renders the chain AND narrates it.)

4. **Present it for review.** Paste the contents of `.cairn/spec/graph.mmd` inline in a
   ```mermaid``` fenced block so it renders, give the prose DAG summary + the build order above.
   **Never make the operator hand-construct the path** — `cairn spec` prints the `file://` URL;
   surface it, AND offer the localhost view + auto-open the interactive graph:
   ```bash
   # Serve the spec dir and open the graph in a new browser window (best-effort, non-blocking).
   ( cd .cairn/spec && python3 -m http.server 8787 >/dev/null 2>&1 & )
   URL="http://localhost:8787/graph.html"
   case "$(uname)" in
     Darwin) open -na "Google Chrome" --args --new-window "$URL" 2>/dev/null || open "$URL" ;;
     Linux)  xdg-open "$URL" >/dev/null 2>&1 || true ;;
     *)      echo "Open manually: $URL" ;;   # Windows: start "$URL"
   esac
   ```
   Always ALSO print the `file://.../graph.html` line as a fallback (headless / no-Chrome / no
   server). Pick a free port if 8787 is taken.

5. **HARD GATE — edit-or-approve + run-policy handoff (MANDATORY).** State this explicitly to
   the operator and STOP:

   > **Review the spec graph.** To adjust: edit `.cairn/tickets/*`, the board
   > (`cairn board set ...` / `cairn board add ...`), or `.cairn/spec/SPEC.md`, then **re-run
   > `cairn spec`** to regenerate the graph — and review again. **OR approve as-is.**
   >
   > **On approval, also pick a run policy** (Factory fuses approval + autonomy into one
   > prompt; so does Cairn — `/cairn-run` enforces the choice at every merge):
   > - `manual` — pause before EVERY merge (**default**; pick this if unsure);
   > - `merge-on-green` — auto-merge a ticket the moment reviewer + tester both PASS;
   > - `full-auto` — no pauses at all; blocked tickets are surfaced at the end of the run.
   >
   > Do **NOT** proceed to `/cairn-run` until the operator explicitly approves. No dispatch,
   > no worktrees, no branches before approval.

   This gate is non-optional. Treat "looks good / approved / go" as the only signal to continue;
   anything else is an edit cycle (adjust → `cairn spec` → re-present). Ask the run-policy
   question via **AskUserQuestion** alongside the approval; an approval that doesn't name a
   policy means `manual`.

## 6. After approval — persist the spec + lock the run policy (MANDATORY)
Approval is not the end of planning. Factory persists approved specs as dated artifacts and
fuses the autonomy decision into the gate; Cairn does both here, before any handoff to
`/cairn-run`.

### 6a. Spec persistence — `.cairn/specs/YYYY-MM-DD-<slug>.md`
Write the approved spec as a dated, git-committable artifact (slug from the goal):

```bash
SLUG=$(printf '%s' "$GOAL" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' \
        | sed 's/^-*//; s/-*$//' | cut -c1-60)
# Same symlink rule as every other .cairn write: refuse a planted symlink at
# the dir or leaf before creating anything (mirrors the worktree guard).
if [ -L ".cairn/specs" ]; then echo "error: .cairn/specs is a symlink (refusing)"; exit 1; fi
mkdir -p .cairn/specs
SPEC_PATH=".cairn/specs/$(date +%F)-${SLUG}.md"
if [ -L "$SPEC_PATH" ]; then echo "error: $SPEC_PATH is a symlink (refusing)"; exit 1; fi
```

Contents: the approved `SPEC.md` narrative, the topological build order, the chosen run policy,
and a `## Tickets` section linking **every** ticket ID to its spec file
(`- T01 — <title> → .cairn/tickets/T01.md`). This artifact is the durable record of WHAT was
approved — it belongs in git. Remind the operator to commit it (you scaffold; the operator
commits, per the Rules).

### 6b. Run policy → `.cairn/config.json`
Persist the gate's choice. The file may already carry other keys (e.g. `models`) — NEVER
clobber them; read-modify-write:

```bash
# $CHOICE is manual | merge-on-green | full-auto (from the gate; default manual)
python3 - "$CHOICE" <<'PY'
import json, pathlib, sys
p = pathlib.Path(".cairn/config.json")
cfg = json.loads(p.read_text()) if p.exists() else {}
cfg["autonomy"] = sys.argv[1]
cfg.setdefault("models", {})
p.write_text(json.dumps(cfg, indent=2) + "\n")
PY
```

jq fallback if `python3` is unavailable:

```bash
[ -f .cairn/config.json ] || printf '{}\n' > .cairn/config.json
jq --arg a "$CHOICE" '.autonomy = $a | .models //= {}' .cairn/config.json \
  > .cairn/config.json.tmp && mv .cairn/config.json.tmp .cairn/config.json
```

`/cairn-run` reads `autonomy` at setup: `manual` pauses before every merge; `merge-on-green`
auto-merges when reviewer + tester pass; `full-auto` never pauses and surfaces blocked tickets
at the end.

### 6c. Per-role model routing (optional — mention it once)
Tell the operator they may also set per-role models in the same file — cheap-worker /
strong-validator economics (Factory Mission-Mode parity); `/cairn-run` passes each role's model
to its Task dispatch:

```json
{"models": {"implementer": "sonnet", "reviewer": "opus", "tester": "haiku"}}
```

Edit it with the same read-modify-write pattern as 6b. Absent roles inherit the session model.

## Rules
- Single-writer: only you (this planning session) write `.cairn/` here. Append to schema/map;
  never clobber operator edits.
- No commits/pushes without operator permission. You scaffold files; the operator commits.
