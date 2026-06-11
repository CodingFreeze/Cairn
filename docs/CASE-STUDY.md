# Case study: Cairn, dogfooded

> How Cairn went from v0.1 to v0.2 — by being run on real work, breaking in
> specific ways, and shipping a fix for every break. Three acts: a small CLI
> project that surfaced sixteen friction findings, a sixteen-ticket DAG that
> stress-tested the spec graph at production scale, and the session deaths
> that shaped v2's continuation machinery.

The shortest honest summary: **every load-bearing feature in v0.2 exists
because v0.1 failed at it in front of us.** The atomic `cairn merge`, the
init scaffolding, the unborn-base guard, the run-lock, the `base_sha`
invariant — none of these came from a whiteboard. They came from running the
loop, hitting the wall, and writing the wall down.

---

## Act 1 — the first real run: a tip calculator

The first end-to-end dogfood target was deliberately boring: a Python CLI tip
calculator. Three tickets — a pure calculation core, an argparse front-end
that consumes it, and packaging with a console-script entry point. Small
enough to finish in one sitting; real enough that git, worktrees, merges, and
the vault all had to actually work.

### What the loop got right immediately

- **Decomposition held.** Three tickets with a clean dependency chain; the
  board's `next` picker walked them in order without intervention.
- **Worktree isolation held.** Each implementer worked in its own worktree
  against a recorded base; review and tests gated each merge.
- **The vault did its job.** Every ticket's decisions folded into
  `vault/decisions.md`; the finished repo carried its own reasoning. Fourteen
  tests green on main, per-ticket `--no-ff` merge history, nothing pushed.

### What broke — sixteen findings, three rounds

Running the loop for real produced sixteen distinct friction findings across
three dogfood rounds. Most were small (a silent `board set`, a doubled ticket
id in graph labels, a copy-paste URL that had to be hand-constructed). Three
were structural, and they tell the story:

**1. The gitignore scaffolding gap.** `cairn init` on a greenfield repo
shipped no `.gitignore`. The baseline commit happily tracked Python bytecode
caches — and on the second ticket's rebase-before-merge, main had deleted a
cache file the ticket branch still "modified". A modify/delete conflict on
pure junk derailed a merge mid-flight. The fix shipped: `init` now scaffolds
a stack-aware, marker-fenced `.gitignore` block (bytecode, build dirs,
`.cairn/worktrees/`) so a whole class of spurious worktree-merge conflicts
can't happen.

**2. The goal-as-path bug.** The planning command passed the project goal —
a full English sentence — to `cairn init` as a positional argument. The CLI's
positional was a *path*. Result: a directory literally named after the goal
sentence, with a `.cairn/` inside it. The command doc and the CLI contradicted
each other, and the contradiction was invisible until someone ran both. The
fix shipped: `init` takes `--goal` as a named flag and persists it to
`vault/goal.md`, so the goal is stored, not misparsed.

**3. The manual-merge footgun.** Integrating a finished ticket took five
hand-run steps: commit the worktree's changes, rebase on base, `--no-ff`
merge, fold the summary into the vault, remove the worktree. Five steps means
five places to half-apply — and a shell-quoting slip produced exactly that, a
merge left partially done. The fix shipped: **`cairn merge <ID>`**, one atomic
command that runs the whole sequence and fails clean — on conflict, the board
is untouched and nothing is half-applied.

A fourth finding deserves a mention because it is so cheap to hit: a fresh
`git init` leaves the default branch *unborn* (zero commits), and
`git worktree add` fails on it with a raw git error. The fix shipped: the run
loop now detects an unborn base and tells you to make a baseline commit, in
plain language, before anything is dispatched.

### The pattern

Every finding followed the same arc: **hit it → write it down → ship the
fix → grow the test suite.** The suite went from 315 to 326 tests in the
first fix pass, and stands at 425 in v0.2. The friction notes were not a
retrospective written after the fact — they were the backlog. The tool was
built by being used.

---

## Act 2 — the Driftwatch-scale test

A three-ticket toy proves the loop runs. It doesn't prove the *spec graph*
works — the part you stare at before approving sixteen tickets of someone
else's plan. For that, Cairn's graph was rebuilt against a real benchmark: a
production agent session (from Factory, the platform that inspired Cairn —
see the README) planning **Driftwatch**, an API-drift monitor decomposed into
a sixteen-ticket DAG.

What made Driftwatch a good stress test wasn't the node count. It was the
**contract structure**: six of the sixteen tickets define data contracts —
config, snapshot model, diff representation, classification output, report
shape, status/history store — that downstream tickets inherit. Get one wrong
and the change ripples through five tickets. The benchmark session treated
this as the spine of the plan:

- **Schema tickets flagged explicitly**, distinguished from tickets that
  merely *consume* a contract.
- **A named lock-first chain** — config → snapshot → diff → classification →
  report/status — called out as "review these contracts before any downstream
  work", with the diff→classify→report segment flagged as the highest-risk
  coupling.
- **Hard-to-reverse choices asked before approval** — runtime, storage,
  dashboard style — because those answers change ticket internals.
- **A topological build order** stated up front, executed strictly: each
  ticket integrated in dependency order so every dependent built on merged
  work.

Cairn's v1 graph fell short of that bar — a flat box diagram with no contract
layer. So the graph was rebuilt, and the rebuilt generator was proven by
rendering the full Driftwatch DAG with it. The result ships in this repo as
[`examples/spec-graph/`](../examples/spec-graph/): a self-contained,
offline interactive HTML graph — layered top-down layout (rank = dependency
depth), schema badges on contract-defining tickets, schema-coupling edges in
solid accent versus plain ordering edges in gray dash, and the lock-first
schema chain rendered bright with a focus toggle that dims everything else.
The benchmark session listed its critical chain in prose; **Cairn draws it.**

The workflow lessons landed too: planning now asks the hard-to-reverse
questions at an explicit gate and locks the answers into `vault/decisions.md`
before decomposition, then narrates the topological build order and names the
deepest produce→consume fan-out so the riskiest contracts get reviewed first.
The board itself learned the contract model — `schema`, `produces`,
`consumes` per ticket — so the graph is generated from data, not vibes.

Sixteen nodes, six contracts, readable at a glance. That's the scale gate
the spec graph now has to clear, and the example is committed so future
changes can't quietly regress below it.

---

## Act 3 — what it proved about continuation

Here is the part that can't be staged: **sessions died while Cairn was being
built, and Cairn's own vault and board are what let the next session
continue.** Context windows compacted mid-feature. Terminals closed with a
ticket dispatched and a worktree dirty. Each time, a fresh session read the
board, read git, and picked up — and each time the resume was bumpy, the
bump became a v2 mechanism:

- **The loop moved out of prose and into the CLI.** v1 described the
  reconciler loop in a command document an agent re-derived each turn — which
  means a resumed session could re-derive it slightly differently.
  v2 extracted the state machine into tested commands: `cairn step` performs
  one atomic iteration (pick ready ticket → worktree → record base →
  flip board → emit dispatch), so a resume executes the same machine the
  dead session was running, not a paraphrase of it.
- **`run-lock` exists because two sessions once both believed they were the
  orchestrator.** A resumed session and a not-quite-dead one reconciling the
  same board is a race; the single-run token (exclusive create) closes it.
- **The `base_sha` invariant exists because "branch exists" is ambiguous.**
  After a crash, an untouched ticket branch looks identical to abandoned
  work unless you recorded what it was cut from. v2 makes `base_sha`
  required at dispatch — the one fact that lets reconciliation distinguish
  "never started", "in flight", and "finished but the board missed it",
  including the nasty crash window between a merge landing and the board
  recording it.

The claim Cairn makes — *kill the terminal mid-run; a new session picks up
exactly where it left off* — is not aspirational. It is a description of how
this repo was developed. The scars are the spec.

### Formalizing it: the continuation benchmark

Anecdotes about resumed sessions are still anecdotes. The next step is
[`evals/`](../evals/) — a continuation benchmark that kills runs at
adversarial points (mid-dispatch, mid-merge, between merge and board write)
and measures whether a cold session reconverges to the correct state. That
work is **in progress** on its own branch and not yet merged; when the
results land, they'll be published here. Until then, this case study is the
evidence: three dogfood rounds, sixteen findings, sixteen fixes, and a tool
that finished building itself across the very session deaths it was designed
to survive.
