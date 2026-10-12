# Changelog

Notable changes to the skills and the `okf_normalize` engine. Dates are release dates.
The engine reports its own version with `ai/scripts/okf --version`.

## 2026-10-12 — lk 1.0.0: `lk-` rename, OKF v0.2 vocabulary, `lk-audit-knowledge`, `lk-doctor`, `govern-work` removed

**`okf_normalize` engine 0.9 (OKF standard 0.2)** · all skills renamed `lk-*` and stamped
`version: 1.0.0` · two new skills · `govern-work` removed from the package · repo root `VERSION` file

Born from one afternoon on a real project: a build-orchestration tool filed one note per
*paragraph* of six completion reports, and the bundle woke up with 118 well-formed, near-empty
`pattern` notes that `okf --check` passed. The docs pointed at an `/audit-knowledge` skill nobody
had written, an installed engine had drifted from the repo clone, and the normalizer still claimed
OKF 0.1 while upstream had moved to 0.2 — with a `status` enum ours contradicted. This release
fixes each of those at the root, and removes the tool that did the filing from the package.

### Breaking — read before upgrading
- **Skills are renamed with an `lk-` prefix** (*local knowledge*) so they group together in
  `~/.claude/skills`: `lk-init-ai-workspace`, `lk-backfill-memory`, `lk-end-session`,
  `lk-reference`, plus the new `lk-audit-knowledge` and `lk-doctor`. Every
  slash reference, shim default (`~/.claude/skills/lk-*`), template and hook path follows. Old
  unprefixed installs keep working until deleted; project shims that point at the old names break
  the moment they are. Order: `lk-doctor --sync-from <clone> --yes`, then `--fix-shims --yes` in
  each project, then `--remove-legacy --yes`. `/lk-doctor` names every step for you.
- **OKF v0.2 vocabulary.** The bundle now speaks the spec's own keys and `--check` treats the old
  ones as drift until `ai/scripts/okf --apply` migrates them (every migration is listed in the
  dry run first):

  | legacy | v0.2 |
  |---|---|
  | `timestamp` / `updated` | `generated: {by, at}` (`by` = the actor rules below) |
  | `source: "a; b"` | `sources: [{resource: a}, {resource: b}]` |
  | `status: unverified` / `verified` / `stale` | `status: draft` / `stable` / `deprecated` (the spec's only values; absent = stable) |
  | `status: open` / `closed` (open-questions) | `draft` / `deprecated` |
  | `verified_on: DATE` | `verified: [{by: human:<id>, at: DATE}]` + `stale_after: DATE + 90d` |

  Why: OKF v0.2 defines `status` as `draft | stable | deprecated` with *absent meaning stable*, so
  our `status: unverified` was an invalid value a strict consumer could read as "stable" — the
  opposite of what it meant. Trust now lives where the spec puts it: a `human:` actor in
  `verified` is the human-reviewed tier; machine output is `draft` with `generated.by` naming the
  producer (`claude-code/<model-id>`, `lk-backfill-memory/1.0`).
- **`okf --review` lists `status: draft`; `okf --promote PATH...` is the only thing that writes a
  `verified` entry.** It refuses a non-`human:` actor. Nothing else — no tool, no agent — sets
  `stable`. Actor resolution: `--actor`, else `actor = human:<id>` in `ai/okf.conf`, else
  `human:<git user.name>`, else `human:unknown`.
- **A deprecated note whose successor relation resolves does not warn.** An open-question
  superseded by a decision note (`deprecated` + `relates <decision>`) is a normal lifecycle end,
  not rot; only an orphaned deprecation is flagged.

### Added
- **`skills/lk-audit-knowledge/`** — the quality pass the docs had promised. `audit_knowledge.py`
  (pyyaml only) finds machine bursts (≥5 notes of one type, one source, one day), low-information
  bodies, near-duplicates, passed `stale_after` / deprecated-but-still-linked notes, drafts never
  promoted after 30 days, orphans, and one type dominating a bundle. Verbs: a read-only report,
  `--json`, `--plan OUT.md` (an editable `action | path | reason` table with a suggested action
  per note) and `--apply PLAN.md` (`git rm` or a backup move for delete; edits only the status
  line for deprecate; merge-into and promote are printed, never done; refuses the whole plan if
  any path leaves the bundle). The workflow: the script
  suggests, the agent reads every flagged note and edits the plan, a human approves, then
  `--apply`, `okf --reindex`, `okf --check`. Reads legacy and v0.2 frontmatter, so it works
  mid-migration. Measured on the project that prompted it (135 notes before cleanup): it proposed
  deleting exactly the 118 land-time notes and flagged none of the 17 real ones beyond orphan hints.
- **`skills/lk-doctor/`** — the system check. `lk_doctor.py [--skills-dir D] [--repo CLONE]
  [--project DIR] [--json]` prints PASS/WARN/FAIL per check with a one-line fix and exits 0 (no
  FAIL) / 1 / 2 (usage). Install checks: every lk skill present and versioned; leftover unprefixed
  copies; sha256 drift against the repo clone; the normalizer on OKF 0.2; backticked `/skill`
  references in any SKILL.md that name no installed skill (this is what would have caught
  `/audit-knowledge`, `/resume-session` and `--doctor-age`); python + pyyaml for the shims;
  `cleanupPeriodDays` ≥ 365. Project checks: `ai/okf.conf`, whether the `okf` shim resolves
  to a real engine, legacy vocabulary (WARN) and invalid v0.2 status values (FAIL), `okf_version`
  on the root index, a promotion queue over 25. Fix verbs, each a dry run until
  `--yes`: `--sync-from CLONE [--prune]`, `--remove-legacy` (only once each `lk-` counterpart is
  installed), `--fix-shims`.
- **`okf_normalize.py` 0.9:** `--promote`; `--actor`; root `index.md` gets `okf_version: "0.2"`
  frontmatter on `--reindex`; `LK_VERSION`; `correction` joins `TYPE_ENUM` (lk-end-session had
  been writing `correction_` notes the engine never accepted, so `--gate` failed on them);
  trust-shape checks (`stable` with no `verified` entry, non-spec actor, passed `stale_after`).
- Root `VERSION` (`1.0.0`) and `version: 1.0.0` in every SKILL.md so `lk-doctor` can compare.
- **`tests/test_skill_docs.py`** — the docs-versus-code contract. Every `/skill` a SKILL.md
  mentions must exist, every `--flag` the docs tell the agent to run must exist in that
  script's argparse, every template `lk-init-ai-workspace` says to copy must ship, every
  relative link must resolve, every SKILL.md must carry the release `version`. All three
  phantoms found this release (`/audit-knowledge`, `/resume-session`, `--doctor-age`) would
  have failed it on the July commit.
  Its first run found two more: the cross-skill links to `transcript-safety.md` still pointed
  at the pre-rename `reference/` dir, and `lk-init-ai-workspace` Phase 3 has told agents since
  July to copy `SYSTEMS.template.md`, `SETUP.template.md` and `PLAN.template.md` — none of
  which had ever been committed. All three now ship.

### Removed
- **`govern-work` is no longer part of this package.** It was the optional fourth skill since
  2026-07-25: a deny-list guard, drift detector, ratchet and a `mint`/`verify`/`land`/`abort`
  contract runner over git worktrees. It governs agent *builds* and only *consumes* the knowledge
  base, so it never belonged in a package whose one promise is a local, git-tracked knowledge base
  — and it was the tool that filed the 118 junk notes. It lives on as its own standalone repo. With
  it go `lk-init-ai-workspace`'s Phase 2.6 scaffolding (the `ai/scripts/gov` shim, the
  `ai/contracts/_TEMPLATE-*.md` templates, the `govern_*` keys in `okf.conf.template`, the
  `<!-- govern-work -->` CLAUDE.md section) and every `gov` check in `lk-doctor`. Projects that use
  it keep working: their shim points at wherever that skill is installed, not at this package.
  `open-question` stays in `TYPE_ENUM` — it is a general concept, closed by a `decision` note.

### Changed
- Upstream moved: every link now points at `GoogleCloudPlatform/open-knowledge-format` (the old
  `knowledge-catalog/okf` tree is a frozen snapshot carrying a "moved" banner).
- `lk-end-session` Phase 5 asks for a one-line `lk-doctor` summary instead of the `--doctor-age`
  flag the engine never had; `/resume-session` and `/audit-knowledge` references point at things
  that exist. `CAPTURE.template.md`, `KNOWLEDGE-SYSTEM.md`, `README.md` and the open-question
  template describe the v0.2 frontmatter.
- `TYPE_ENUM`: `gotcha, workaround, schema, decision, pattern, runbook, reference, open-question,
  correction`.
- `--gate` is still built for a Stop hook, but no hook ships in this package any more; wiring one
  is a project choice.


## 2026-07-25 — `govern-work` (the enforcement layer)

**`okf_normalize` engine unchanged (still 0.8)** · new skill `govern-work` (`govern.py`,
`govern_contract.py`) · `TYPE_ENUM` gains `open-question` · 58 `init-ai-workspace` tests (was 57)
· 76 new `govern-work` tests

The three existing skills are a **capture** system: they record knowledge after the fact and say
so, plainly, in their own Limitations section — nothing forces the recording to happen. This
release adds a fourth, optional skill that supplies the enforcement layer: a deny-list guard, a
drift detector, a ratchet, and a `mint`/`verify`/`land`/`abort` contract runner over git
worktrees, so the highest-value disciplines move to a mechanically checked boundary instead of
staying something an agent has to remember to do mid-work.

### Added
- **`skills/govern-work/`** — the new skill. `govern.py` (stdlib + pyyaml, same as
  `okf_normalize.py`): `--open`, `--rule`, `--lint-spec`, `--ratchet`, `--baseline`, `--drift`,
  `--gate`. `govern_contract.py`: `mint` / `verify` / `land` / `abort`, over real `git worktree`s.
  `gov.shim.sh` — the ~10-line `ai/scripts/gov` project shim, same interpreter-probe convention as
  `okf.shim.sh`. `hooks/pre-commit` — the deny-list guard, exact-match only, inert outside a
  contract. `hooks/stop-gate.sh` — the Stop hook this repo's own README says it does not ship;
  this is that hook, calling `gov --gate`. Full doctrine and every verb:
  [`skills/govern-work/SKILL.md`](skills/govern-work/SKILL.md).
- **`okf_normalize.py`'s `TYPE_ENUM` gains `open-question`** (`gotcha, workaround, schema,
  decision, pattern, runbook, reference, open-question`) — a one-line, explicitly scoped addition
  so `gov --open`'s notes pass `okf --check`/`--gate` like every other concept type, instead of
  permanently showing a "type outside our enum" drift line. `open-question` is a fork nobody has
  decided yet; `gov --rule` closes one into a `type: decision` note carrying the ruling verbatim.
- **`init-ai-workspace` scaffolds `govern-work` into a project when that skill is installed**
  (Phase 2.6 — idempotent, marker-gated, create-only, same mechanism as every other phase): the
  `ai/scripts/gov` shim, `ai/contracts/_TEMPLATE-contract.md` +
  `ai/contracts/_TEMPLATE-open-question.md`, a `govern-work settings` block appended to
  `ai/okf.conf` (flat `govern_`-prefixed keys, same teaching tone as the existing `archive =`
  block), and a separate `<!-- govern-work -->` marker section in root `CLAUDE.md` carrying a
  `## Verify` placeholder that `gov mint` refuses against until a human fills it in. If no
  `govern_verify_command` is configured, prints a one-time teaching block explaining that without
  one, `gov land` can certify "the ledger is complete" but never "the work is correct" — keyed off
  the missing config key, never off "no tests" (a docs/research repo legitimately has none).
- **README**: `govern-work` as the fourth skill, its own honesty note (advisory-strength, not
  airtight — a contracted agent with a shell can bypass every guard here; this raises the floor
  from briefing discipline to mechanical default, not to airtight, which needs sandboxing and is
  out of scope), and a day-zero note (a fresh adopter's real first week is `--lint-spec` + the
  contract runner + the ledger gate; `--drift`/`--ratchet` earn their keep as history accrues).

### Changed
- **`KNOWLEDGE-SYSTEM.md`'s Limitations section** — two items partially struck, precisely scoped
  to what `govern-work` actually closes (not to "review is now forced" or "capture is now
  automatic," neither of which is true): the unbounded promotion queue is now bounded by
  `gov --ratchet`/`--baseline` (review itself is still manual); capture-of-decisions is now
  mandatory for any work routed through `gov land`'s ledger gate (ordinary, non-contracted
  sessions are still fully operator-dependent, unchanged).

## 2026-07-15 — disclosure controls (safety release)

**`distill_transcript 0.1` → `0.2`** · new `ai/okf.conf` · 57 tests (was 51)

Archiving conversations made a decision's *why* citable. It also made it possible to publish a
conversation by accident. This release makes that a deliberate, enforced choice with a safe default,
and fixes an instruction that told the agent to write secrets down.

### Fixed — read this one
- **`/end-session` Phase 3 instructed the agent to record "every key, cookie, env var".** The
  capture protocol says the opposite (*"Secrets — point to where they live, never paste them"*), and
  Phase 3 is labelled the highest-value phase, so it's the one that got followed. It was an
  instruction to write credentials into a runbook the system then tells you to commit. Phase 3 now
  says to record **where** a credential lives and **how to refresh it**, never the value, and notes
  that a secret in git history must be rotated rather than deleted.

### Added
- **`ai/okf.conf` with `archive = off | local | shared`**, and `okf.conf.template` written by
  `/init-ai-workspace` — plain-English, aimed at someone who doesn't think about this daily.

  | mode | behaviour |
  |---|---|
  | `local` **(default)** | archive to `ai/<session>/raw/`, gitignored — never pushed |
  | `shared` | archive **and commit** — private repos, informed choice only |
  | `off` | don't archive; decisions then have no citable source |

- **Enforcement, not advice.** `distill_transcript.py` calls `git check-ignore` *before writing* and
  **refuses** to create an un-gitignored transcript under `local`. The raw `.jsonl` is refused in
  **every** mode — it holds every tool result (env dumps, file contents, command stdout). A file
  that is never written cannot be committed by mistake.
- **Fails safe.** Missing, garbled, or empty config → `local`. A typo must never silently upgrade a
  project to publishing its conversations.
- **`/init-ai-workspace` Phase 2.5 — decide what leaves this machine.** Detects repo visibility
  (`gh repo view --json visibility`) and, for a public repo, recommends gitignoring `ai/<session>/`
  or all of `ai/` — stating plainly that this forfeits "survives a fresh clone", and that the trade
  is correct because an unreviewed publish is worse than a lost note.
- **README safety section** in plain language: push is permanent, rotate don't delete, the scanner
  finds shapes not secrets, and public repos should keep the knowledge base local.
- `--mode` flag to override the config for a single run.

### Warnings
- **`0 hits` from the secret scan means "nothing obvious", never "safe to publish".** Passwords,
  connection strings, PII, and internal hostnames have no detectable shape.
- **A leaked credential must be rotated, not deleted.** Git keeps history; forks and clones keep
  copies. Removing the file changes nothing.
- **Existing projects have no `ai/okf.conf`** and therefore behave as `local` — safe, but if you
  were relying on distilled transcripts being committed, re-run `/init-ai-workspace` and choose
  `shared` deliberately.

## 2026-07-15 — conversation provenance

**engine `0.7` → `0.8`** · new tool `distill_transcript.py 0.1` · 51 tests (was 33)

`source: src/auth/login.ts:42` works when a fact lives in code. A **decision**'s *why* was argued in
a conversation — cited as prose (`session 2026-06-19`) nobody can open it, so the note becomes
unfalsifiable. Non-code work (analysis, dashboards, ops) is mostly decisions, so this was the common
case, not a corner. Two compounding failures, both now closed.

### Added
- **`/end-session` Phase 0 — archive the transcript.** Runs first, so every later phase has a real
  citation target instead of citing its own summary. Writes two files per session:

  | File | Contents | Git |
  |---|---|---|
  | `ai/<session>/raw/<id>.md` | human + assistant prose (~4% of raw) | **committed** — the citation target |
  | `ai/<session>/raw/<id>.jsonl` | untouched transcript | **gitignored** — holds tool output |

- **`distill_transcript.py`** (stdlib-only) and the `ai/scripts/okf --distill` shim verb. Resolves
  the session by UUID glob under `~/.claude/projects/` rather than deriving the project directory
  from cwd — Claude Code mangles the cwd (non-alphanumerics → `-`), which differs between a Windows
  path and its git-bash view of the same directory. The UUID is unambiguous on every platform.
- **Known-shape secret scan** over the distilled prose: `ghp_`/`gho_`, `sk-ant-`, `sk-`, `AKIA`,
  `AIza`, `xox[baprs]-`, `sk_live_`, `glpat-`, `npm_`, `dop_v1_`, JWTs, PEM blocks. Hits are
  redacted and reported. It never prints "clean" — see Warnings.
- **`/init-ai-workspace` reports transcript retention** at scaffold time (Phase 0) and offers to
  raise `cleanupPeriodDays`. Scaffolds `ai/<session>/raw/` and the `.gitignore` rule for `*.jsonl`.

### Changed
- **`check_provenance` no longer exempts `session`/`plan` sources** (`okf_normalize.py`). Any
  `source:` that is prose, or names a path that doesn't resolve, now warns:
  ```
  ? `source` names a session/plan in prose, not a resolvable path -- cite the archived transcript
  ? `source` path not found: ai/session/raw/deadbeef-....md
  ```
  URLs are still skipped: reachability needs the network, and a chat URL that outlives its project
  reshuffle can't be proven either way from here.
- `/end-session` anti-patterns now name the three ways this fails in practice: citing a session in
  prose, committing the raw `.jsonl`, and reading `0 hits` as "safe to commit."

### Fixed
- `test_check_provenance_clean_when_ok` asserted that `source: session 2026-06-11` produced **zero**
  warnings — the suite pinned the bug in place as correct behavior. Rewritten against a resolvable
  transcript, plus coverage for prose sources, pruned transcripts, and URL skipping.

### Warnings
- **Upgrading to `0.8` will surface warnings on existing notes.** Any note citing a session in prose
  starts failing `--check`. That's the point — those citations were never checkable — but it is not
  a silent upgrade. Run `ai/scripts/okf --check` after updating.
- **Archiving only protects sessions from the day you adopt it.** Claude Code deletes session files
  older than `cleanupPeriodDays` ([default 30](https://code.claude.com/docs/en/settings)) at
  startup. Transcripts already past that are unrecoverable, and raising the setting doesn't bring
  them back. `/backfill-memory` cannot mine what no longer exists.
- **`secret scan: 0 hits` is not a clearance.** It means no *issuer-formatted* token was found.
  Passwords, connection strings, PII, internal hostnames, and proprietary data have no detectable
  shape. Read a distilled transcript before committing it.
- **Never invert the git split.** The `.jsonl` carries every tool result — `env` dumps, file
  contents, command stdout. Tool output is ~31% of a raw transcript's bytes and effectively all of
  its secret exposure. The distilled `.md` is the committable artifact.
- **The distilled record holds no tool output by design.** "We chose X because the benchmark showed
  Y" keeps the claim, not Y. The local raw `.jsonl` is the fallback, and it does not survive a clone.
- **Only Claude Code writes an archivable transcript.** On claude.ai / Cowork the source is a chat
  that no `source:` can durably resolve.

## 2026-07-14 — initial public release

`okf_normalize 0.7`, OKF standard `0.1`, 33 tests.

Three skills — `init-ai-workspace` (scaffold + normalize), `backfill-memory` (seed from static
assets, cite or drop), `end-session` (capture against the three deaths of context) — over an
[Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
bundle, extended with `source` / `status` / `**Verify:**` anti-rot discipline. Graph viewer vendored
from GoogleCloudPlatform/knowledge-catalog (Apache-2.0).
