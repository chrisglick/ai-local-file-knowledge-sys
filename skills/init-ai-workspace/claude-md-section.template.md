<!-- knowledge-system -->
## Knowledge system

Durable knowledge lives in-repo, visible, git-tracked.

**At session start:**
1. Open `ai/README.md` — the **index of indexes**: it names every index/log/projection
   (`RESUME.md`, `{{STATUS}}`, `ai/memory/index.md`, `ai/{{SESSION_DIR}}/`, `ai/plans/`) and says
   which to read for your situation. Decide which index you need first; don't load them all.
2. Resuming a thread → `RESUME.md`. New/broad context → `{{STATUS}}` then skim
   `ai/memory/index.md` (cheap TOC); open only the atomic files you need. Run a note's
   `**Verify:**` before trusting load-bearing claims.

**When you learn something durable / at session end:** follow `ai/CAPTURE.md`. Timeless facts
→ atomic file in the right `ai/memory/<topic>/` (`gotcha_`/`schema_`/`decision_`/`pattern_`/`runbook_`/`reference_`)
in the CAPTURE.md frontmatter format; time-based narrative → `ai/{{SESSION_DIR}}/`; status changes →
`{{STATUS}}`. Capture decisions + the why.

**OKF upkeep (`ai/memory/` is an OKF bundle):** the `index.md` files are **generated** — a PostToolUse
hook regenerates them on every note edit, so never hand-edit an index. Conformance batches into
`/end-session`, which runs `ai/scripts/okf --apply` + `--check` (frontmatter, provenance, links).
Use `ai/scripts/okf --move SRC DST` to relocate a note (rewrites links), `--touch <note>` after
editing, `--render` for the graph. The engine/viewer are global tools; this repo carries only the
`ai/scripts/okf` pointer. `/end-session` runs the capture protocol.
<!-- /knowledge-system -->
