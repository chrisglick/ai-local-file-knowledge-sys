# `ai/` — knowledge home & index of indexes

Everything an agent or human needs to resume work on {{PROJECT}} without re-deriving it or
blindly trusting it. Plain markdown, git-tracked, visible (not a dotfolder), owned by this
repo — survives a clone, portable to any tool.

This file is the **index of indexes**: it doesn't hold knowledge, it points at the things
that do. Each index below owns exactly one kind of state. **The one rule: decide which
index you need first.** Don't drag the whole system through every task — open the cheapest
index that answers your question, drill down only on demand.

## The indexes (what owns what)

| Index | Where | Kind | Owns — single source of truth for… | Mutability |
|-------|-------|------|------------------------------------|------------|
| [`RESUME.md`](../RESUME.md) | repo root | **packet** | the active thread: one-line state, the *single next action*, what's true right now, landmines, auth preconditions | overwritten each session |
| [`{{STATUS}}`](../{{STATUS}}) | repo root | **projection** | current project + plan status. **The only place for plan-status tables** (they drift if copied). | updated every session |
| [`memory/index.md`](memory/index.md) | `ai/memory/` | **fact index** | TOC over the timeless wiki — gotchas, schema/constants, decisions, patterns, runbooks | +1 line per new note |
| [`{{SESSION_DIR}}/`]({{SESSION_DIR}}/) | `ai/{{SESSION_DIR}}/` | **event log** | dated narrative — what happened, why decided, pick-up state (append-only) | frozen (never edited) |
| [`plans/`](plans/) | `ai/plans/` | **spec set** | feature specs, the build-period design for each plan | frozen when built |
| [`CAPTURE.md`](CAPTURE.md) | `ai/` | **protocol** | *how* to write knowledge — where each kind goes, provenance + `**Verify:**` rules | rarely |

`memory/` itself is flat by design: the file **prefix is the type** — `gotcha_` (operational
traps / known issues), `schema_`, `decision_`, `pattern_`, `runbook_`. No subfolders;
`memory/index.md` + `grep` is the structure. `research/` (if present) holds one-off write-ups.

## Which index do I open? (decide the tier first)

| Your situation | Read | Then stop unless… |
|----------------|------|-------------------|
| Resuming a specific in-flight task | **`RESUME.md`** — and run its named `Verify` checks | …you need broader context → status |
| New to the project / broad context | **`{{STATUS}}`** → **`memory/index.md`** | …a specific fact is needed → drill into the atomic file |
| Need a durable fact (gotcha, schema, command) | **`memory/index.md`** → the atomic file → run its **`Verify:`** | trust only after Verify passes |
| "Why / when did X happen?" | **`{{SESSION_DIR}}/`** (newest first) | the decision's *why* may also be a `decision_` note in memory |
| Building / understanding a plan | **`plans/`** (the plan spec) + status for its state | — |
| Recording a learning / ending a session | **`CAPTURE.md`** (or run `/end-session`) | — |

**Trust rule:** every fact carries its provenance and a `Verify:` check. Distilled notes are
cheap and stable; the only net-negative note is a *confidently wrong* (stale) one — so verify
load-bearing claims before acting, especially anything naming a file, flag, or value.

## Start here
1. Resuming work → `../RESUME.md`. New here → `../{{STATUS}}` then `memory/index.md`.
2. Recording a learning → `CAPTURE.md`.
3. Ending a session → `/end-session`.
