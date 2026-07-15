# Knowledge System: init · backfill · end-session

In-repo, git-tracked, provenance-checked knowledge base. Goal: distill a fact once, retrieve cheaply (don't re-derive from code/chat each session).

Flow: `init` (scaffold) → `backfill` (seed, once) → `end-session` (capture, every session). All write `ai/memory/` through `okf_normalize.py`, reached per-project via the `ai/scripts/okf` shim.

## The three skills

| Skill | Does | When |
|---|---|---|
| `init-ai-workspace` | Scaffold + normalize the `ai/` structure. Idempotent, non-destructive. | Onboard a project / fix format drift |
| `backfill-memory` | Bulk-seed memory from static assets (notes, DB schema, config, code). Capped campaigns. Output is `status: unverified`. | Once, on un-distilled history |
| `end-session` | Capture this session; beat the 3 deaths of context (chat ends / one machine / fresh clone). | Every session close |

`init` + `end-session` = operator-incremental. `backfill` = one-time mining.

## `ai/` folder structure

```
project-root/
├── README.md   # human front door; <!-- knowledge-system --> block links into ai/
├── CLAUDE.md   # agent router; same marker; open ai/README.md FIRST at session start
├── RESUME.md   # active thread: state + single next action (overwritten each session)
├── STATUS.md   # project + plan status; the ONE place for plan-status tables
└── ai/
    ├── README.md   # INDEX OF INDEXES: points at every index; no knowledge itself
    ├── CAPTURE.md  # capture protocol: where each kind goes + provenance rules
    ├── memory/     # the OKF bundle (timeless wiki)
    │   ├── index.md       # generated TOC (reserved; no frontmatter)
    │   └── TYPE_slug.md…  # atomic concept notes (folded by topic once earned)
    ├── plans/      # feature specs / build-period design (frozen when built)
    ├── session/    # dated journal (append-only, frozen); or sessions/
    ├── scripts/okf # 10-line shim → global engine/viewer
    └── okf-memory-graph.html   # generated viewer output (gitignored)
```

- Two front doors: root `README.md` (human), root `CLAUDE.md` (agent). Same `<!-- knowledge-system -->` marker → `init` is idempotent.
- `ai/README.md` = index of indexes. Names every index, says which to open per situation. Rule: decide which index first.
- Read-order: resume task → `RESUME.md`; broad context → `STATUS.md` → `memory/index.md`; durable fact → `memory/index.md` → atomic file → run its `Verify`; "why X?" → `session/`; build a plan → `plans/`.

## Where knowledge lives

| Kind | Lives in | Mutability |
|---|---|---|
| Active thread (state, next action, landmines, auth) | `RESUME.md` (root) | overwritten / session |
| Current status (project + plan tables) | `STATUS.md` (root) | updated / session |
| Timeless facts (gotcha/schema/decision/pattern/runbook) | `ai/memory/` | edited in place |
| Dated narrative (what happened, why, pick-up state) | `ai/session/` | frozen |
| Build specs | `ai/plans/` | frozen when built |

Rule: still true in 6 months → `ai/memory/`; "what we did on a date" → `ai/session/`. Denormalize the timeless (cache enums/IDs/table names), query the live (never cache counts / deploys).

## Concept types (`ai/memory/`)

Note `type` = filename prefix = OKF `type` value.

| `type` | Captures |
|---|---|
| `gotcha` | operational trap / non-obvious behavior |
| `workaround` | temporary fix (vs permanent `gotcha`); superseded via `relations` |
| `schema` | stable values/structure to cache (enums, IDs, table/layout) |
| `decision` | posted intent + why (+ supersedes) |
| `pattern` | reusable engineering shape |
| `runbook` | exact command sequence |
| `reference` | pointer to external resource (URL/dashboard/ticket/key path) |

## Other memory store

Global `~/.claude/.../memory/` (`user`/`feedback`/`project`/`reference`): machine-local, opaque, not cloned. `ai/memory/` is canonical + portable; global is fallback when no `ai/memory/`.

## OKF format

`ai/memory/` = literal [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf) (OKF) bundle: markdown + YAML frontmatter, one concept/file, non-empty `type`.

```yaml
---
type: gotcha                      # OKF-required (non-empty); the one hard rule
title: Short human title          # OKF-recommended
description: one-line hook        # OKF-recommended; = this note's index line
timestamp: 2026-06-19T00:00:00Z   # OKF-recommended; ISO 8601, last meaningful change
created: 2026-06-19               # set-once
source: src/auth/login.ts:42      # our extension; provenance (mandatory)
status: unverified                # our extension; verified | unverified | stale
valid_as_of: 2026-06-19           # optional; as-of date for a snapshot fact
verified_on: 2026-06-19           # optional; --check warns after 90d
tags: [auth]                      # optional; viewer tag filter
relations:                        # optional; typed edges
  - supersedes auth/decision_old-flow.md   # supersedes|extends|refines|contradicts|relates|duplicates
---

Distilled fact. Inline link related notes: [refresh flow](runbook_refresh-token.md).

**Action:** what to DO.
**Verify:** command / file:line / check that confirms it's still true.
```

- `type` is the only hard requirement. `description`/`timestamp`/`tags` recommended; `source`/`status`/`Verify` are our extensions (OKF tolerates unknown keys). Don't stub optional fields.
- Reserved (no frontmatter): `index.md` (lowercase TOC), optional `log.md`.
- Graph = inline body links, not the index. No body links → disconnected dots.
- Decision body: `Decision (NAME, DATE)` / `Why` / `Supersedes`.
- Flat until ~20–25 notes, then fold by topic/domain (not by type; type stays in prefix).

## Engine: `okf_normalize.py` (v0.7, OKF v0.1)

One file, `pyyaml`-only. Lives once in the `init-ai-workspace` skill dir; hooks in `~/.claude/hooks/`; project carries only the 10-line `ai/scripts/okf` shim. Nothing vendored → one engine to upgrade.

| Verb | Purpose |
|---|---|
| `--check` / `--gate` | strict conformance / mechanical-drift-only |
| `--apply` | rewrite frontmatter to canonical form |
| `--reindex` | regenerate `index.md` from frontmatter |
| `--move SRC DST` | move a note + rewrite inbound links |
| `--review` | print `status: unverified` promotion queue |
| `--suggest-links` | surface note pairs not yet linked |
| `--render` | regenerate graph HTML |

Indexes + graph are generated, never hand-written (`--reindex`; prose above `<!-- okf-index:auto -->` preserved). Viewer vendored from Google's `knowledge-catalog` enrichment-agent, Apache-2.0.

## Disciplines

- Provenance or drop: every claim → quoted source slice; no cite = dropped.
- Machine writes `unverified`; only a human promotes (`--review` queue).
- Adversarial verify: grep the cited quote exists; skeptic subagent for high-stakes.
- Idempotent / non-destructive: append marker-gated; `git mv` keeps history.
- Check git every session (untracked = lost on clone).
- Conformance via tool, not hand-edit.

## Strengths

- External standard + versioned tool → no format drift.
- Every note falsifiable (`source` + `Verify`); staleness detectable.
- 3 entry points: scaffold / bulk-seed / incremental.
- Human-gated: machine output can't read as verified.
- One engine; tiny per-project footprint (data + 10 lines).
- In-repo, portable, survives a clone.

## Limitations

- Operator-dependent; capture is not automatic.
- Promotion queue unbounded; nothing forces review → unvouched facts accumulate.
- No auto-merge; dedup is manual.
- Anti-hallucination gate is prompt-enforced, not guaranteed (codebase adapter = highest risk).
- Graph edgeless unless notes inline-linked; `--suggest-links` is a hint.
- Foldering heuristic needs human correction.
- Decay only warns (90d), no re-verify.
- Tooling global, not vendored: clone lacks engine unless skill installed (shim exits 127); `--gate` hook global.
- OKF v0.1; value-carrying extensions are local; other OKF tools ignore them.
- Cross-platform friction (Windows backslash paths, case-insensitive FS rename).

## Bottom line

Trust rests on discipline + human review, not mechanism. Failure mode = a growing `unverified` queue + an edgeless graph, not a crash. Good scaffold for diligence, not a substitute for it.

## Sources (external)

- Open Knowledge Format (OKF) — Google Cloud Platform `knowledge-catalog`, Apache-2.0: <https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf>. Standard the bundle targets; graph viewer vendored from its `enrichment_agent`.
- Note-shape prior art: `cq` knowledge commons (summary→detail→action, confirm-or-decay), `beads` (typed relations), Zep bi-temporal model (`valid_as_of`).
