# How to Capture Knowledge (the protocol)

How an agent (or human) records what a session learned so it is not regenerated from
scratch next time. Read at session start; follow at session end (`/end-session` runs it).

Governing idea: **distill once, retrieve cheaply.** Re-deriving project facts each session
(re-reading code, re-searching, re-reasoning) is expensive *and non-deterministic*. A
distilled, provenance-tagged note is cheap and stable. The only thing that makes a note
net-negative is being **confidently wrong** (stale) — so every note carries its source and
a way to re-verify it.

---

## The two axes — where things go

> When copying this file, substitute `{{SESSION_DIR}}` with the project's session journal dir —
> `session` (singular, canonical default) or `sessions` (plural) — whichever already exists.

| Kind | Lives in | Nature |
|------|----------|--------|
| Time-based — what happened, decisions, pick-up state | `ai/{{SESSION_DIR}}/YYYY-MM-DD-topic.md` | Append-only journal. Frozen after. |
| Time-based — feature specs during a build | `ai/plans/*.md` | Frozen after the build. |
| Timeless — gotchas, constants, decisions, patterns, runbooks | `ai/memory/*.md` + `ai/memory/index.md` | A wiki. Deduplicated, edited in place. |
| Current status | the project status doc (root) | Single source of truth. Updated every session. |

Rule of thumb: still true in six months → `ai/memory/`. "What we did on this date" → `ai/{{SESSION_DIR}}/`.

**Denormalize the timeless, query the live.** Cache slow-changing facts (enum values, IDs,
table names) as `schema_*` files — cheaper and more deterministic than a lookup every session.
Do NOT cache live state (counts, what's deployed) — query that at runtime; a cache goes stale.

---

## Atomic file format (`ai/memory/*.md`) — literal OKF + our extensions

One concept per file. Filename = `TYPE_short-kebab-slug.md`, TYPE ∈
`gotcha | workaround | schema | decision | pattern | runbook | reference` (our enum doubles as the OKF `type` value).

```markdown
---
type: gotcha | workaround | schema | decision | pattern | runbook | reference  # OKF-required, non-empty
title: Short human title
description: one-line hook (mirrors this note's index line)   # the "summary" of the fact
timestamp: YYYY-MM-DDT00:00:00Z                         # ISO 8601 — LAST meaningful change (formerly `updated`)
created: YYYY-MM-DD                                      # set-once; never edited after
valid_as_of: YYYY-MM-DD                                  # OPTIONAL — as-of date for a snapshot fact
source: <file:line | plan-N | session YYYY-MM-DD | URL> # extension — provenance (mandatory)
status: verified | unverified | stale                   # extension — anti-rot
verified_on: YYYY-MM-DD                                  # OPTIONAL — when a human last confirmed; decays >90d
tags: [topic, area]                                     # OPTIONAL — only if you'll use the viewer filter
relations:                                               # OPTIONAL — typed edges to other notes
  - supersedes old/decision_x.md                         #   verb ∈ supersedes|extends|refines|contradicts|relates|duplicates
---

The distilled fact, stated plainly (the "detail"). Short. Link related notes inline: [other note](type_slug.md).

**Action:** what to DO about it (the actionable takeaway — esp. for gotcha/workaround/pattern).
**Verify:** the exact command / file:line / check that confirms this is still true.
```

`type` is the only field OKF *requires*; we additionally require `source` + `**Verify:**` — the
anti-rot mechanism (a note without provenance is worth less than no note). `description` / `timestamp`
are OKF-recommended; `created`, `tags`, `valid_as_of`, `verified_on`, `relations` are optional — add
each only when it carries weight (don't stub them).

### Note shape & lifecycle (refinements from agent-memory prior art — cq, beads, Zep)

All are validated by `--check`:

- **summary → detail → action** (cq): `description` is the summary, the body is the detail, an
  `**Action:**` line says what to do. Most valuable on `gotcha`/`workaround`/`pattern`.
- **Typed `relations`** (beads/cq): declare the *kind* of edge — `supersedes | extends | refines |
  contradicts | relates | duplicates` + a resolving path; `--check` validates the verb + target.
- **`workaround` type** (cq lifecycle.kind): a TEMPORARY fix, distinct from a permanent `gotcha`; when
  tooling makes it obsolete, the replacement carries `relations: [supersedes <workaround>]`.
- **Decay** (cq confirm-or-decay): set `verified_on` when promoting to `status: verified`; `--check`
  warns once it's >90 days old. Anti-rot with a clock.
- **`valid_as_of`** (Zep bi-temporal, lite): the as-of date for a snapshot fact.

Deliberately skipped: numeric confidence scores + multi-org aggregation (YAGNI for a single-author
wiki); verbatim store-everything (we distill on purpose).

## OKF is the standard (`ai/memory/` is an Open Knowledge Format bundle)

This bundle targets [OKF](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
literally — a published, external standard, deliberately chosen so the format is *not yours to
drift*. The frontmatter above **is** the standard; don't invent variants. Rules:

- **Reserved files** carry no frontmatter: `index.md` (the TOC — lowercase) and optional `log.md`
  (a changelog). All other `.md` are concepts.
- **`type` is the one hard OKF rule** — every concept needs a non-empty `type`.
- `description` / `timestamp` (ISO 8601) / `tags` are OKF-recommended and kept populated.
- `source` / `status` / `**Verify:**` are *our extensions* — OKF tolerates unknown keys, so
  conforming to OKF does **not** cost the anti-rot discipline. Keep them.
- **Link related notes inline.** OKF builds its graph from markdown links *inside* concept bodies
  (`[other note](type_slug.md)`), not from `index.md` (skipped). A bundle whose connections live
  only in the index renders as disconnected dots. Cross-link notes to each other in their bodies.

**Enforcement — don't hand-maintain conformance.** Run the `/init-ai-workspace` conformance pass
(`okf_normalize.py`): it rewrites `updated→timestamp`, derives `description` from the index hook,
adds `tags`, and flags a legacy `INDEX.md` for rename to `index.md` plus any off-convention filename. Dry-run first, then `--apply`.

## Capturing "posted intent" (decisions + the why)

User directives, corrections, preferences, and **rejected options** are the highest-value
capture. Record each as a `decision_*.md`:

```markdown
**Decision (NAME, YYYY-MM-DD):** what was decided.
**Why:** the reasoning (a decision without its why gets re-litigated).
**Supersedes:** the prior belief/approach this overrides, if any.
```

---

## Layout — flat until it earns folders, then by topic
Notes fold **by topic/domain** (`clients/`, a subsystem, a workstream), not by type — you retrieve
"everything about X" (a schema + a decision + a runbook), which type-folders would scatter. Type
stays in the `TYPE_` filename prefix + `type:` frontmatter. Keep a bundle **flat until ~20–25 notes**
(or until one topic would hold ≥5); a 1-file topic dir is noise — leave generic/cross-cutting notes
at the root. Concept-id is the path (`topic/schema_x`); cross-dir links bundle-absolute (`/topic/x.md`),
same-dir links relative.

## Indexes are generated, never hand-written
`index.md` (root + per-topic) is **derived from concept frontmatter** by `okf_normalize.py --reindex`.
Durable prose lives above the `<!-- okf-index:auto -->` marker (preserved); below it is regenerated.

## Write procedure (session end / when a learning lands)
1. **Scan `ai/memory/index.md` first** — if a note exists, EDIT it (don't duplicate).
2. If it contradicts an existing note, fix or mark the old one `status: stale` and say what misled you.
3. Write/edit the atomic file (in the right topic dir) with full frontmatter + `**Verify:**`; link any
   genuinely related note inline in the body.
4. **Regenerate indexes:** `okf_normalize.py ai/memory --reindex` (don't hand-edit the index).
5. (Optional) propose it to a shared knowledge commons (e.g. `cq`) — `ai/memory/` is the durable source.

## Read procedure (session start)
1. Read `ai/memory/index.md` (cheap TOC) → drill into the relevant topic's `index.md`.
2. Open only the atomic files relevant to the task.
3. Before acting on a note that names a file/flag/value, run its `**Verify:**` check.

## What NOT to capture
- Anything derivable from code or `git log`.
- Anything that only matters to one conversation.
- Live/volatile metrics (status doc or runtime query instead).
- Secrets — point to where they live (SSM, key paths), never paste them.
