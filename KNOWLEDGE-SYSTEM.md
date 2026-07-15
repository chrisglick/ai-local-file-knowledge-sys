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
    │   └── raw/           # archived transcripts — the citation target for a decision's "why"
    │       ├── <id>.md    #   distilled prose (committed; ~4% of raw)
    │       └── <id>.jsonl #   untouched transcript (GITIGNORED — holds tool output)
    ├── scripts/okf # 10-line shim → global engine/viewer/distiller
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
| Verbatim conversation (what was *actually* said) | `ai/session/raw/<id>.md` | immutable; the source |
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

## Conversation provenance (the `why` has a source too)

`source: src/auth/login.ts:42` works when the fact lives in code. A **decision** doesn't: its *why*
was argued in a conversation. Cite that as prose (`session 2026-06-19`) and nobody can ever open it
— the note becomes unfalsifiable, which is the one thing this bundle exists to prevent. Non-code
work (analysis, dashboards, ops) is *mostly* decisions, so this is the common case, not the corner.

Two failures compound:
1. **Prose sources rot silently** — no path, no check, no way to know the note drifted from reality.
2. **The source disappears.** Claude Code deletes session files older than `cleanupPeriodDays`
   (**default 30**) at startup. The citation dangles on day 31 — exactly when you'd want it.

So `/end-session` Phase 0 archives the session into the repo, and `--check` treats a prose or
unresolvable `source:` as a warning. A distilled transcript is to a decision what a commit hash is
to code: the note may be wrong, but you can always walk back to what was said.

**What gets archived, and how far it travels.** `ai/okf.conf` sets `archive = off | local | shared`;
absent or garbled falls back to `local`, because a typo must never upgrade a project to publishing
its conversations. `local` is the default — it beats `cleanupPeriodDays` (the actual problem) while
nothing leaves the machine. `shared` (commit the distilled record so citations resolve on a clone)
is an informed choice for private repos, never for public ones.

The config is **enforced, not advisory**: `distill_transcript.py` refuses to write an un-gitignored
transcript under `local`, and refuses the raw `.jsonl` in *every* mode. `git check-ignore` answers
before anything is written, so a transcript that could be committed is never created. This matters
because the system's standing weakness is prompt-enforced discipline — this control is code + git.

| File | Contents | Git | Size |
|---|---|---|---|
| `<id>.md` | human + assistant prose | committed under `shared`; ignored under `local` | ~4% of raw |
| `<id>.jsonl` | untouched transcript | **never committed, in any mode** — tool output | 100% |

Tool results (`env` dumps, file reads, command stdout) are ~31% of a raw transcript's bytes and
carry essentially all of its secret exposure; the conversation itself is ~3%. The distiller drops
tool results, tool calls, and reasoning **by block type** — a structural exclusion, deterministic in
a way secret-scanning is not. (Load-bearing subtlety: a `tool_result` block carries
`role: "user"`. Filtering turns by role instead of block type archives every command's output.)

A known-shape secret scan (`ghp_`, `sk-ant-`, `AKIA`, JWTs, PEM blocks…) runs over the distilled
prose and redacts hits, because people paste keys into chat. It is **defense in depth, not a
clearance**: passwords, connection strings, PII, and internal hostnames have no detectable shape, so
`0 hits` means "no issuer-formatted token," never "safe." Read the file before committing it.

## Engine: `okf_normalize.py` (v0.8, OKF v0.1)

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
| `--distill` | archive this session's transcript as a citable record (`distill_transcript.py`) |

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
- Transcript archiving is per-session and manual: sessions before adoption are unrecoverable once
  `cleanupPeriodDays` (default 30) has pruned them, and raising the setting protects only what's left.
- The distilled record holds no tool output by design — "we chose X because the benchmark showed Y"
  keeps the claim, not Y. The local raw `.jsonl` is the fallback, and it doesn't survive a clone.
- Secret scanning covers issuer-formatted tokens only. Passwords, connection strings, PII, and
  internal hostnames are undetectable — committing a distilled transcript is a human judgement call.
- Only Claude Code writes a transcript we can archive. On claude.ai / Cowork the source is a chat
  that no `source:` can durably resolve.
- Tooling global, not vendored: clone lacks engine unless skill installed (shim exits 127); `--gate` hook global.
- OKF v0.1; value-carrying extensions are local; other OKF tools ignore them.
- Cross-platform friction (Windows backslash paths, case-insensitive FS rename).

## Bottom line

Trust rests on discipline + human review, not mechanism. Failure mode = a growing `unverified` queue + an edgeless graph, not a crash. Good scaffold for diligence, not a substitute for it.

## Sources (external)

- Open Knowledge Format (OKF) — Google Cloud Platform `knowledge-catalog`, Apache-2.0: <https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf>. Standard the bundle targets; graph viewer vendored from its `enrichment_agent`.
- Note-shape prior art: `cq` knowledge commons (summary→detail→action, confirm-or-decay), `beads` (typed relations), Zep bi-temporal model (`valid_as_of`).
