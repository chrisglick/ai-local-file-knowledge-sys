---
name: init-ai-workspace
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
  "migrate .ai to ai", "/init-ai-workspace", or onboarding a project to the knowledge system.
  (Complements the built-in /init, which only generates CLAUDE.md from code.)
---

# init-ai-workspace — standardize a project's knowledge structure

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

Run the phases in order. Use `pwd`/repo root as the target unless the user names one.

---

## Phase 0 — Detect current state (report before acting)
Check and report:
- Folder: does `.ai/` exist? `ai/`? both? neither?
- `git rev-parse --is-inside-work-tree` — is it a git repo? (affects rename method)
- Root `CLAUDE.md` — exists? does it already contain the marker `<!-- knowledge-system -->`?
- Root `README.md` — exists? does it already contain the marker `<!-- knowledge-system -->`?
- Root `RESUME.md` — exists? (created here as a stub if absent; `/end-session` overwrites it.)
- Project **status doc** — `STATUS.md` at root? a different name/path? Note it; it's `{{STATUS}}`
  in the templates (default `STATUS.md`). If none exists, the index will still point at the
  intended path — flag that the project should start one.
- `ai/memory/index.md` — exists? (or a legacy uppercase `INDEX.md` — note it; Phase 4 renames it to
  the OKF-reserved lowercase `index.md`.) `ai/CAPTURE.md`? `ai/README.md`? If `ai/README.md` exists
  but is an older "folder map" (no index-of-indexes / no situation read-order table), offer to upgrade it.
- Session journal dir — does `ai/session/` (singular) or `ai/sessions/` (plural) already exist?
  Note which spelling is in use; you will **reuse it**, not create the other variant.
Summarize what will be created/migrated/skipped, then proceed.

---

## Phase 1 — Migrate `.ai/` → `ai/` (only if `.ai/` exists; approval-gated)
Skip entirely if there's already an `ai/` and no `.ai/`. If `.ai/` exists:

1. **Collision safety check** — never rewrite a `.ai` domain URL (e.g. `mem0.ai/`):
   `grep -rn '[A-Za-z0-9]\.ai/' --include='*.md' --include='*.ts' --include='*.mjs' --include='*.json' --include='*.sh' --include='*.html' --exclude-dir=node_modules --exclude-dir=.git .`
   If any hits are real domains, exclude those files/lines from the sed below (do them by hand).
2. **Check for untracked files** under `.ai/`: `git status --porcelain .ai/ | grep '^??'`.
   `git mv` only moves tracked files — move any untracked stragglers with plain `mv` afterward.
3. **Rename (git repo):** `git mv .ai ai` — then move untracked leftovers: `[ -d .ai ] && mv .ai/* ai/ 2>/dev/null; [ -d .ai ] && rmdir .ai`.
   **Non-git:** plain `mv .ai ai`.
4. **Update forward-slash references** across text files (safe after the collision check):
   `grep -rlZ --include='*.md' --include='*.ts' --include='*.mjs' --include='*.json' --include='*.sh' --include='*.html' --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=dist '\.ai/' . | xargs -0 -r sed -i 's#\.ai/#ai/#g'`
5. **Update Windows backslash references** (`...\.ai\...`) — sed backslash escaping is unreliable;
   find them with `grep -rn '\.ai\\' --include='*.md' .` and fix each with an exact Edit
   (`\.ai\` → `\ai\`). Don't forget any external memory/notes index that names the path.
6. **Verify zero stragglers:** `git grep -n '\.ai[/\\]' -- ':!node_modules'` must return nothing.

---

## Phase 2 — Scaffold the `ai/` structure (create only what's missing)
Create dirs if absent: `ai/`, `ai/memory/`, `ai/plans/`, `ai/scripts/`, and the session journal dir.

**Tooling is global, not vendored.** The engine (`okf_normalize.py`), the graph viewer (`okf-viewer/`),
and the Stop hook live ONCE in this skill dir / `~/.claude/hooks/` — never copy them into a project.
The only per-project "script" is a 10-line pointer: copy this skill's **`okf.shim.sh`** to
`ai/scripts/okf` (create only if absent) and `chmod +x` it. It resolves the global engine/viewer and
defaults the bundle to `ai/memory`, so commands are just `ai/scripts/okf --check` / `--reindex` /
`--render`. Add `ai/okf-memory-graph.html` (the viewer's regenerable output) to `.gitignore`.

**Session dir spelling — reuse, don't duplicate:** both `ai/session/` (singular, canonical
default) and `ai/sessions/` (plural) are valid. If either already exists, use that one and
do NOT create the other. Only when neither exists, create `ai/session/`. Whichever spelling
is in play, use it consistently in the README, CAPTURE, and CLAUDE.md text you write below
(`{{SESSION_DIR}}` in the templates = the chosen dir name).
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
`description`, `timestamp` (ISO 8601), `tags`, plus our `source`/`status` extensions and a
mandatory `**Verify:**` line; the `decision_` "posted intent" format with **Why:**/**Supersedes:**;
denormalize-the-timeless / query-the-live; write-procedure = check `index.md` first, edit-don't-dupe,
flag stale, add the `index.md` pointer, link related notes inline; read-procedure = read `index.md`
at start, verify-on-use; and what NOT to capture — anything derivable from code/git, volatile
metrics, or secrets).

The scaffolded `ai/memory/` is an **[Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
(OKF) bundle** — a published external standard (markdown + YAML frontmatter, non-empty `type` per
concept), extended with our `source`/`status`/`**Verify:**` anti-rot discipline (OKF tolerates the
extra keys). The CAPTURE template carries the canonical frontmatter; the **reserved index file is
lowercase `index.md`** and carries no frontmatter. Phase 4 normalizes an existing bundle to this
standard. (The OKF graph viewer is a GLOBAL tool in this skill dir — `okf-viewer/render.py`, reached
per-project via the thin `ai/scripts/okf --render` shim; it is NOT vendored into each project.)

**`ai/memory/index.md`** — the wiki TOC (OKF-reserved; no frontmatter):
```markdown
# Memory Index (timeless wiki TOC)

Scan first; open only the files you need. One line per note. Add a pointer here whenever
you create a file in `ai/memory/`. Format/rules: [`../CAPTURE.md`](../CAPTURE.md).

## Gotchas (operational traps)
## Schema / Constants (stable values — cache, don't re-look-up)
## Decisions (posted intent + the why)
## Patterns (recurring engineering shapes)
## Runbooks (exact command sequences)
```

**`RESUME.md`** (repo **root**, not `ai/`) — the T0 resumption packet. Create a stub ONLY if
absent (if it exists, leave it — `/end-session` owns this file): copy this skill's
`RESUME.template.md` and substitute `{{PROJECT}}` / `{{STATUS}}`. This keeps the index of
indexes' `../RESUME.md` link from dangling on a fresh workspace; `/end-session` Phase 9
overwrites the stub with real active-thread state.

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

## Phase 4 — OKF conformance pass (normalize an existing bundle; approval-gated)
Bring an existing `ai/memory/` to the literal-OKF standard so the format stops drifting between
sessions. **Skip if `ai/memory/` has no concept files yet** (a fresh scaffold is born conformant).
This phase has the same discipline as Phase 1: detect → report → get a yes → fix → verify.

The mechanical engine is this skill's **`okf_normalize.py`** (deps: `pyyaml` only). It splits the
work: it **rewrites frontmatter** itself, and only **reports** renames (which need repo-wide
reference fixups — those are your job, below).

1. **Dry-run report (never mutate first):**
   `python <skill-dir>/okf_normalize.py ai/memory`
   It lists per-file frontmatter changes (`updated→timestamp`, `description` derived from the
   `index.md` hook, `tags: []` added), any concept it **can't** fix (missing `type`, or no index
   hook to source a `description` from — a human must write those), a `RENAMES:` block
   (`INDEX.md→index.md`, off-convention filenames), and — if the bundle is flat and ≥~20 concepts —
   a `SUGGESTION:` block with a rough slug-token tally to seed foldering (step 5).
2. **Show the user the report and get approval** before any write. If files need a human-written
   `description`/`type`, surface them — don't invent prose.
3. **Apply frontmatter:** `python <skill-dir>/okf_normalize.py ai/memory --apply`.
4. **Perform the renames with reference fixups** (the dangerous part — a bare `mv` corrupts links):
   for each rename in the report, `git mv OLD NEW` (or `mv` if non-git), then rewrite every inbound
   reference across the repo — `index.md` body links, `CLAUDE.md`, `README.md`, sibling notes,
   sessions, plans. Reuse Phase 1's grep-then-sed recipe (and hand-Edit Windows backslash paths).
   For `INDEX.md→index.md` on a case-insensitive filesystem, rename via a temp
   (`git mv INDEX.md _index.tmp && git mv _index.tmp index.md`) so the case change actually takes.
5. **Fold by topic if the bundle has earned it** (the dry-run prints a `SUGGESTION:` when flat and
   ≥~20 notes). The script's slug-token tally is a **rough hint, not the answer** — it mislabels
   token accidents (`lapsed-acme-*` → `lapsed`) and can't tell that related domains belong in one folder
   (e.g. a `db` note really belongs with `infra`) or spot domain-less notes. **Read the notes and refine it:** fold by
   **topic/domain** (`acme/`, `billing/`), keep the `TYPE_` prefix, file singletons into the right
   cluster's folder, leave generic/cross-cutting notes at root. Foldering is **placement only** —
   `git mv` (or `mv`) each whole note into its topic dir, dropping a now-redundant topic token from
   the slug, and rewrite inbound refs. **Never combine note contents** — one concept per file is
   invariant; deduping two notes about the same fact is a *separate* capture-time step, not foldering.
   **Propose the refined mapping and get a yes — don't auto-bucket.** Skip for small/flat bundles.
6. **Regenerate indexes (generated, never hand-written):**
   `python <skill-dir>/okf_normalize.py ai/memory --reindex` — emits root + per-topic `index.md`
   from concept frontmatter, preserving prose above the `<!-- okf-index:auto -->` marker.
7. **Verify clean:** re-run the dry-run — 0 frontmatter changes, 0 renames pending. Then
   `git grep -n 'INDEX\.md'` should return nothing in tracked files (frozen session notes excepted).
8. **Regenerate the graph** with the global viewer: `ai/scripts/okf --render` (or
   `python <skill-dir>/okf-viewer/render.py ai/memory ai/okf-memory-graph.html`). It's nesting-aware
   (hierarchical concept-ids); the HTML output is a per-project artifact (gitignore it).

Conformance is enforced by the tool, not by hand — re-running this phase is the idempotent check.

## Phase 5 — Verify & report
- `git grep -n '\.ai[/\\]'` returns nothing (if a migration ran).
- **OKF conformance** (if Phase 4 ran): `python <skill-dir>/okf_normalize.py ai/memory` reports 0
  changes / 0 renames pending, and `git grep -n 'INDEX\.md'` returns nothing.
- **Index of indexes resolves:** every link in `ai/README.md` points at a real path —
  `../RESUME.md`, `../{{STATUS}}`, `memory/index.md`, `{{SESSION_DIR}}/`, `plans/`, `CAPTURE.md`.
  (If `{{STATUS}}` doesn't exist yet, flag it: the project should start its status doc.)
- **Both front doors wired:** root `README.md` and `CLAUDE.md` each contain one
  `<!-- knowledge-system -->` block pointing at `ai/README.md`.
- The structure exists; list what was **created**, **migrated**, **kept** (skipped) —
  including `RESUME.md` (stub vs kept) and the root-`README.md` section (created vs appended vs kept).
- **Durability reminder:** new files are untracked until committed — *untracked = lost on a
  fresh clone.* Recommend (and offer) a focused commit of the `ai/` scaffolding, honoring the
  repo's commit rules. Do not commit without the user's go-ahead.

## Anti-patterns
- Overwriting an existing `CAPTURE.md`/`CLAUDE.md`/memory file. (Create-only; append for CLAUDE.md.)
- Creating `ai/session/` next to an existing `ai/sessions/` (or vice-versa) — fragments the journal.
  Detect the existing spelling and reuse it; only default to `session/` when neither exists.
- Running the rename sed before the domain-collision check.
- Blanket-sed'ing backslash Windows paths (escaping breaks) — Edit those by hand.
- Declaring done without `git grep` proving zero `.ai/` stragglers.
- Committing the rename tangled with unrelated working-tree changes without flagging it.
- Renaming a memory file (or `INDEX.md→index.md`) with a bare `mv` and leaving inbound links
  dangling — every rename needs the repo-wide reference fixup (Phase 4 step 4).
- Inventing `description`/`type` text the normalizer flagged as missing — derive from the index
  hook or ask; an invented one-liner is worse than an empty field.
- Hand-editing frontmatter to "fix conformance" instead of running `okf_normalize.py` — that's how
  format drift starts.
- Reading "group/merge related domains" (foldering) as *combine note files*. Foldering moves whole
  files into topic dirs; it NEVER concatenates contents. One concept per file is invariant; merging
  two notes that cover the same fact is a separate, deliberate dedup at capture time.
