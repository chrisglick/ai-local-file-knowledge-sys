# Changelog

Notable changes to the skills and the `okf_normalize` engine. Dates are release dates.
The engine reports its own version with `ai/scripts/okf --version`.

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
