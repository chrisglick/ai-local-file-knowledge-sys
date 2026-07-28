# Phase 4 — OKF conformance pass (loaded only when `ai/memory/` already has concept files)

Loaded by `init-ai-workspace` SKILL.md for the upgrade case: bring an existing `ai/memory/` to the
literal-OKF standard so the format stops drifting between sessions. Same discipline as the `.ai/`
migration: detect → report → get a yes → fix → verify.

The mechanical engine is this skill's **`okf_normalize.py`** (deps: `pyyaml` only). It splits the
work: it **rewrites frontmatter** itself, and only **reports** renames (which need repo-wide
reference fixups — those are your job, below). Conformance is enforced by the tool, not by hand —
hand-editing frontmatter to "fix conformance" is how format drift starts, and re-running this
phase is the idempotent check.

1. **Dry-run report (never mutate first):**
   `python <skill-dir>/okf_normalize.py ai/memory`
   It lists per-file frontmatter changes (`updated→timestamp`, `description` derived from the
   `index.md` hook, `tags: []` added), any concept it **can't** fix (missing `type`, or no index
   hook to source a `description` from — a human must write those), a `RENAMES:` block
   (`INDEX.md→index.md`, off-convention filenames), and — if the bundle is flat and ≥~20 concepts —
   a `SUGGESTION:` block with a rough slug-token tally to seed foldering (step 5).
2. **Show the user the report and get approval** before any write. If files need a human-written
   `description`/`type`, surface them — derive from the index hook or ask; an invented one-liner
   is worse than an empty field.
3. **Apply frontmatter:** `python <skill-dir>/okf_normalize.py ai/memory --apply`.
4. **Perform the renames with reference fixups** (the dangerous part — a bare `mv` corrupts links):
   for each rename in the report, `git mv OLD NEW` (or `mv` if non-git), then rewrite every inbound
   reference across the repo — `index.md` body links, `CLAUDE.md`, `README.md`, sibling notes,
   sessions, plans. Reuse the migration reference's grep-then-sed recipe
   (`reference/migrate-dot-ai.md`, incl. hand-Editing Windows backslash paths).
   For `INDEX.md→index.md` on a case-insensitive filesystem, rename via a temp
   (`git mv INDEX.md _index.tmp && git mv _index.tmp index.md`) so the case change actually takes.
5. **Fold by topic if the bundle has earned it** (the dry-run prints a `SUGGESTION:` when flat and
   ≥~20 notes). The script's slug-token tally is a **rough hint, not the answer** — it mislabels
   token accidents (`lapsed-acme-*` → `lapsed`) and can't tell that related domains belong in one
   folder (e.g. a `db` note really belongs with `infra`) or spot domain-less notes. **Read the
   notes and refine it:** fold by **topic/domain** (`acme/`, `billing/`), keep the `TYPE_` prefix,
   file singletons into the right cluster's folder, leave generic/cross-cutting notes at root.
   Foldering is **placement only** — `git mv` (or `mv`) each whole note into its topic dir,
   dropping a now-redundant topic token from the slug, and rewrite inbound refs. **Never combine
   note contents** — one concept per file is invariant; deduping two notes about the same fact is
   a *separate* capture-time step, not foldering.
   **Propose the refined mapping and get a yes — don't auto-bucket.** Skip for small/flat bundles.
6. **Regenerate indexes (generated, never hand-written):**
   `python <skill-dir>/okf_normalize.py ai/memory --reindex` — emits root + per-topic `index.md`
   from concept frontmatter, preserving prose above the `<!-- okf-index:auto -->` marker.
7. **Verify clean:** re-run the dry-run — 0 frontmatter changes, 0 renames pending. Then
   `git grep -n 'INDEX\.md'` should return nothing in tracked files (frozen session notes excepted).
8. **Regenerate the graph** with the global viewer: `ai/scripts/okf --render` (or
   `python <skill-dir>/okf-viewer/render.py ai/memory ai/okf-memory-graph.html`). It's nesting-aware
   (hierarchical concept-ids); the HTML output is a per-project artifact (gitignore it).
