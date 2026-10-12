---
version: 1.0.0
name: lk-init-ai-workspace
description: >
  Initialize or upgrade any project into the standard in-repo knowledge structure: a
  visible ai/ folder whose README is an index-of-indexes (points at RESUME, STATUS,
  memory wiki + INDEX, session, plans), a root RESUME.md packet, a root README
  "Knowledge & status" front-door section, and a root CLAUDE.md knowledge-system section
  that routes the agent to the index of indexes at session start. Idempotent and
  non-destructive — detects current state, never overwrites existing content, appends
  marker-gated sections to existing README/CLAUDE.md, and offers an approval-gated
  migration of a hidden .ai/ folder to a visible ai/ folder (git mv + safe reference fixups).
  USE WHEN: "initialize ai workspace", "scaffold ai folder", "set up project knowledge",
  "migrate .ai to ai", "/lk-init-ai-workspace", or onboarding a project to the knowledge system.
  (Complements the built-in /init, which only generates CLAUDE.md from code.)
---

# lk-init-ai-workspace — standardize a project's knowledge structure

Gives a project the in-repo, visible, git-tracked knowledge system: timeless learnings in
a wiki, time-based work in a journal, and capture rules the agent reads at session start —
so knowledge is distilled once and retrieved cheaply, not regenerated every session.

## Governing principles (do not violate)
1. **Idempotent** — safe to run repeatedly. Re-running changes nothing already correct.
2. **Non-destructive** — NEVER overwrite an existing file's content. Create only what's missing;
   for CLAUDE.md, *append* a marked section. When unsure, show the diff and ask.
3. **Approval-gated migration** — the `.ai/ → ai/` rename touches many files; show the plan and
   get a yes before running it.
4. **History-preserving** — use `git mv` so renames keep blame/history.

Run the phases in order. Use `pwd`/repo root as the target unless the user names one. The
conditional phases (1, 2.6, 4) each live in a reference file — load one only when its trigger
condition holds.

---

## Phase 0 — Detect current state (report before acting)
Check and report:
- Folder: does `.ai/` exist? `ai/`? both? neither?
- `git rev-parse --is-inside-work-tree` — is it a git repo? (affects rename method)
- Root `CLAUDE.md` — exists? does it already contain the marker `<!-- knowledge-system -->`?
- Root `README.md` — exists? does it already contain the marker `<!-- knowledge-system -->`?
- Root `RESUME.md` — exists? (created here as a stub if absent; `/lk-end-session` overwrites it.)
- Project **status doc** — `STATUS.md` at root? a different name/path? Note it; it's `{{STATUS}}`
  in the templates (default `STATUS.md`). If none exists, the index will still point at the
  intended path — flag that the project should start one.
- `ai/memory/index.md` — exists? (or a legacy uppercase `INDEX.md` — note it; the Phase 4
  conformance pass renames it to the OKF-reserved lowercase `index.md`.) `ai/CAPTURE.md`?
  `ai/README.md`? If `ai/README.md` exists but is an older "folder map" (no index-of-indexes /
  no situation read-order table), offer to upgrade it.
- Session journal dir — does `ai/session/` (singular) or `ai/sessions/` (plural) already exist?
  Note which spelling is in use; you will **reuse it**, not create the other variant.
- `ai/SYSTEMS.md` (external-systems manifest) and root `SETUP.md` (fresh-clone checklist) —
  exist? If absent they're scaffolded in Phase 2.
- **Transcript retention (report this loudly — it has a deadline).** Claude Code prunes session
  transcripts older than `cleanupPeriodDays` (default 30) at startup, and `/lk-backfill-memory`
  cannot mine what no longer exists — see
  [transcript safety](../lk-reference/transcript-safety.md):
  ```bash
  grep -n 'cleanupPeriodDays' ~/.claude/settings.json || echo "unset -> default 30 days"
  ls -1 ~/.claude/projects/*/*.jsonl 2>/dev/null | wc -l   # transcripts still on disk
  ```
  If unset or low, say plainly that older transcripts are already gone, and offer to raise it
  (`"cleanupPeriodDays": 3650`) — a one-line settings edit that protects future sessions only.
Summarize what will be created/migrated/skipped, then proceed.

---

## Phase 1 — Migrate `.ai/` → `ai/` (conditional)
**Only if `.ai/` exists** (skip entirely when there's already an `ai/` and no `.ai/`): read and
follow [`reference/migrate-dot-ai.md`](reference/migrate-dot-ai.md) — the approval-gated,
collision-safe rename with repo-wide reference fixups and the zero-stragglers verification.

---

## Phase 2 — Scaffold the `ai/` structure (create only what's missing)
Create dirs if absent: `ai/`, `ai/memory/`, `ai/plans/`, `ai/scripts/`, and the session journal dir.

**Tooling is global, not vendored.** The engine (`okf_normalize.py`), the transcript distiller
(`distill_transcript.py`), and the graph viewer (`okf-viewer/`) live ONCE in this skill dir — never
copy them into a project. The only per-project "script" is a 10-line pointer: copy this skill's
**`okf.shim.sh`** to `ai/scripts/okf` (create only if absent) and `chmod +x` it. It resolves the
global tools and defaults the bundle to `ai/memory`, so commands are just `ai/scripts/okf --check`
/ `--reindex` / `--render` / `--distill`.

Also create `ai/{{SESSION_DIR}}/raw/` — where `/lk-end-session` archives each session — and write
`ai/okf.conf` from this skill's **`okf.conf.template`** (create only if absent; it records the
`archive` mode chosen in Phase 2.5 below).

**`.gitignore` — a safety boundary, not tidiness.** Write the rules that match the mode:
```gitignore
ai/okf-memory-graph.html          # regenerable viewer output
ai/{{SESSION_DIR}}/raw/*.jsonl    # ALWAYS: raw transcripts hold tool output (env dumps, file reads, stdout)
ai/{{SESSION_DIR}}/raw/*.md       # if archive = local  (the conversation stays on this machine)
```
The `*.jsonl` rule is unconditional in every mode — `distill_transcript.py` refuses to write there
if it isn't ignored (why: [transcript safety](../lk-reference/transcript-safety.md)).

**Session dir spelling — reuse, don't duplicate:** both `ai/session/` (singular, canonical
default) and `ai/sessions/` (plural) are valid. If either already exists, use that one and
do NOT create the other — creating the second variant fragments the journal. Only when neither
exists, create `ai/session/`. Use the chosen spelling consistently in the README, CAPTURE, and
CLAUDE.md text you write below (`{{SESSION_DIR}}` in the templates = the chosen dir name).
Create these files ONLY if they don't already exist (replace `{{PROJECT}}` with the repo/dir name).
If a file exists, leave it untouched and note it as "kept".

**`ai/README.md`** — the **index of indexes** (the entry point that routes to every other
index). Copy this skill's `README.template.md` and substitute `{{PROJECT}}` / `{{SESSION_DIR}}`
/ `{{STATUS}}` (the status-doc path, default `STATUS.md`). It points *up* at the root-level
`RESUME.md` and `{{STATUS}}` via `../`, and *down* at `memory/index.md`, the session log, and
`plans/`, with a "which index do I open?" read-order table.
**Upgrade case:** if `ai/README.md` already exists as an older flat "folder map" (no
index-of-indexes framing, no situation read-order table), show the diff and offer to replace
it with the template — this is the one create-only file worth upgrading in place (approval-gated).

**`ai/CAPTURE.md`** — copy the canonical protocol (the version in this skill's companion
`CAPTURE.template.md` if present, else write the protocol covering: timeless-vs-time-based
split; the literal-OKF atomic file format — `type` (OKF-required, non-empty), `title`,
`description`, `generated` (`{by, at}`), `sources` (`[{resource}]`), `status` (`draft | stable |
deprecated`), `verified`, `stale_after`, `tags`, plus our `created`/`relations` extensions and a
mandatory `**Verify:**` line; the `decision_` "posted intent" format with **Why:**/**Supersedes:**;
denormalize-the-timeless / query-the-live; write-procedure = check `index.md` first, edit-don't-dupe,
flag stale, add the `index.md` pointer, link related notes inline; read-procedure = read `index.md`
at start, verify-on-use; and what NOT to capture — anything derivable from code/git, volatile
metrics, or secrets).

The scaffolded `ai/memory/` is an **[Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format)
(OKF) bundle** — a published external standard (markdown + YAML frontmatter, non-empty `type` per
concept) in its **v0.2 vocabulary** (`generated` / `sources` / `status` / `verified` / `stale_after`),
plus our `**Verify:**` anti-rot line and `created`/`relations` extensions (OKF tolerates the extra keys). The CAPTURE template carries the canonical frontmatter; the **reserved index file is
lowercase `index.md`**; only the root one carries frontmatter, and only `okf_version: "0.2"`. The Phase 4 conformance pass normalizes an
existing bundle to this standard.

**`ai/memory/index.md`** — the wiki TOC (OKF-reserved; `--reindex` stamps `okf_version: "0.2"` on it). Include the
`<!-- okf-index:auto -->` marker exactly as shown below the preamble — `okf_normalize.py --reindex`
requires it before it will regenerate this file (content above the marker is preserved verbatim;
without it, `--reindex` refuses rather than risk clobbering hand-written prose):
```markdown
# Memory Index (timeless wiki TOC)

Scan first; open only the files you need. One line per note. Add a pointer here whenever
you create a file in `ai/memory/`. Format/rules: [`../CAPTURE.md`](../CAPTURE.md).

<!-- okf-index:auto (regenerated by okf_normalize.py --reindex) -->

## Gotchas (operational traps)
## Schema / Constants (stable values — cache, don't re-look-up)
## Decisions (posted intent + the why)
## Patterns (recurring engineering shapes)
## Runbooks (exact command sequences)
```

**`RESUME.md`** (repo **root**, not `ai/`) — the **thin thread index** (one row per thread →
its plan file; detail lives in the plans, never here). Create a stub ONLY if absent (if it
exists, leave it — `/lk-end-session` owns this file): copy this skill's `RESUME.template.md` and
substitute `{{PROJECT}}` / `{{STATUS}}`. This keeps the index of indexes' `../RESUME.md` link
from dangling on a fresh workspace; `/lk-end-session` Phase 9 regenerates the thread table from
plan frontmatter.

**`ai/SYSTEMS.md`** — the declarative manifest of external services, MCPs/skills, and generated
artifacts the project touches (copy `SYSTEMS.template.md`, substitute `{{PROJECT}}`). Fill what
you can detect (git remotes, MCP servers in use, tracker ids in existing notes) and leave the
rest as template rows — `/lk-end-session` Phase 7 keeps it synced; the next session reads it to
know what to poll for external drift. Pointers only, never credential values.

**`SETUP.md`** (repo **root**) — the fresh-clone checklist (copy `SETUP.template.md`). Detect
the silent-failure steps that already exist (a `.githooks/` dir needing `git config
core.hooksPath`, an `.env.example`, a gitignored credentials file) and record them; a step
skipped silently on a fresh clone is exactly what this file prevents. Auth entries are
*pointers* (where it lives, how to refresh, expiry symptom) — never values.

**Plan convention** — `ai/plans/` files are **live per-thread state documents**, not frozen
specs: one thread = one plan = one owner, with `status`/`owner`/`ticket`/`blocked_by`/`as_of`
frontmatter (see `PLAN.template.md`; point `ai/CAPTURE.md` writers at it). Existing plan files
without frontmatter are fine — flag them for `/lk-audit-knowledge` rather than mass-editing here.

---

## Phase 2.5 — Decide what leaves this machine (ASK; never assume)
`/lk-end-session` can save each conversation into the repo so a decision's *why* has a source you can
open — genuinely useful, and also the one part of this system that can **publish something you
didn't mean to publish**. Settle it now, at scaffold time, not at 2am mid-session. Full modes,
enforcement, and the public-repo rules: [transcript safety](../lk-reference/transcript-safety.md).

**Detect first — don't ask a question the repo already answers:**
```bash
git remote -v                                        # any remote at all?
gh repo view --json visibility -q .visibility 2>/dev/null   # PUBLIC | PRIVATE | (blank = unknown)
```

- **PUBLIC** (or heading to a public host): state the rotate-not-delete warning from the
  reference plainly, default to **`archive = local`**, and offer, in order:
  1. **`ai/{{SESSION_DIR}}/` ignored entirely** (journal + transcripts stay local; `memory/` and
     `plans/` commit). Good default: the curated notes are the shareable part.
  2. **All of `ai/` ignored** — local-only knowledge base, for when nobody will review each file
     before pushing. It forfeits "survives a fresh clone" — say so; an unreviewed publish is
     worse than a lost note.
  3. **Commit it, reviewed** — only if the user will actually read each file before every push.
- **PRIVATE**: `archive = local` is still the default; `shared` is a fine, informed choice for a
  team that wants citations to resolve on a clone.
- **Unknown** (no remote, or no `gh`): use `local` — a repo with no remote today gets one tomorrow.

Write the answer to `ai/okf.conf` (`okf.conf.template`) and make `.gitignore` match — the config
is enforced by `distill_transcript.py`, not by memory. State the outcome in one line the user can
check, e.g. *"archive = local — conversations are saved to ai/session/raw/ on this machine and
are gitignored; nothing from a chat will be pushed."*

---

## Phase 3 — Wire the root files (create, or marker-gated append — never overwrite)

Two root-level files orient the two audiences: `CLAUDE.md` routes the **agent**, `README.md`
routes the **human / GitHub view**. Both carry the same `<!-- knowledge-system -->` marker so
re-runs are idempotent.

### 3a — `README.md` (the human front door)
- **No root `README.md`:** create one with the section from `root-readme-section.template.md`
  (substitute `{{STATUS}}`), under an `# {{PROJECT}}` title.
- **Exists, already has `<!-- knowledge-system -->`:** skip.
- **Exists, missing the marker:** *append* the `root-readme-section.template.md` block near the
  top (after the intro, before deep architecture) — do not touch existing content.

### 3b — `CLAUDE.md` (the agent router)
- **No root `CLAUDE.md`:** create it with the section from `claude-md-section.template.md`.
- **Exists, already has `<!-- knowledge-system -->`:** skip (idempotent). If the existing marked
  section still says "skim `ai/memory/index.md`" first (the pre-index-of-indexes wording), offer
  to replace the marked block with the current template (which routes to `ai/README.md` first).
- **Exists, missing the marker:** *append* the section (do not touch existing content).

Use this skill's **`claude-md-section.template.md`** (substitute `{{SESSION_DIR}}` / `{{STATUS}}`).
It routes the agent to `ai/README.md` (the index of indexes) **first**, then to RESUME / status /
`memory/index.md` by situation — matching the index the workspace now exposes.

---

## Phase 4 — OKF conformance pass (conditional)
**Only if `ai/memory/` already has concept files** (a fresh scaffold is born conformant): read
and follow [`reference/okf-conformance.md`](reference/okf-conformance.md) — the approval-gated
normalize pass (`okf_normalize.py` dry-run → apply → renames with reference fixups → optional
topic foldering → `--reindex` → graph).

## Phase 5 — Verify & report
- **If Phase 1 ran:** its step-6 zero-stragglers check passed.
- **If Phase 4 ran:** its step-7 verify is clean (0 changes, 0 renames pending, no `INDEX.md`
  references in tracked files).
- **Index of indexes resolves:** every link in `ai/README.md` points at a real path —
  `../RESUME.md`, `../{{STATUS}}`, `../SETUP.md`, `SYSTEMS.md`, `memory/index.md`,
  `{{SESSION_DIR}}/`, `plans/`, `CAPTURE.md`.
  (If `{{STATUS}}` doesn't exist yet, flag it: the project should start its status doc.)
- **Both front doors wired:** root `README.md` and `CLAUDE.md` each contain one
  `<!-- knowledge-system -->` block pointing at `ai/README.md`.
- The structure exists; list what was **created**, **migrated**, **kept** (skipped) —
  including `RESUME.md` (stub vs kept) and the root-`README.md` section (created vs appended vs kept).
- **Durability reminder:** new files are untracked until committed — *untracked = lost on a
  fresh clone.* Recommend (and offer) a focused commit of the `ai/` scaffolding, honoring the
  repo's commit rules. Do not commit without the user's go-ahead.
