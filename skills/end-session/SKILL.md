---
name: end-session
description: >
  Structured session close-out that captures the full scope of a working session so it
  survives the three ways context dies: the conversation ending, single-machine state, and
  a fresh git clone. Runs a fixed pipeline — reconstruct what happened, write the pick-up
  state, run the 6-month cold-read test, audit git/durability, sweep memory, log loose ends,
  sync docs/dashboards, and ask the human the things only they know.
  USE WHEN: ending a work session, "close the session", "wrap up", "end session", "/end-session",
  "are we done", or before a long break.
---

# End Session — capture everything before the context is gone

A long session generates expensive, perishable context. This skill exists because **valuable findings are routinely lost** — not because nobody wrote a summary, but because the summary missed the *operational* details (how to run it, where the auth is, whether the work is even committed) that a returning agent actually needs.

## The governing principle
Context dies three ways. Your capture must beat all three:
1. **The conversation ends** → write it to disk, not just chat.
2. **State is on one machine** → durable files persist locally + in memory, but only on *this* machine.
3. **A fresh clone has only committed files** → if it's untracked, it's gone. **Check git, every time.**

> The test for "captured enough": *Could a competent agent with zero memory of this session resume the work tomorrow — and could a different person on a fresh clone resume it in six months?* If either answer is no, you're not done.

## Project conventions (check first)
If the project has an **`ai/CAPTURE.md`**, it governs *where* and *how* knowledge is stored — follow it. In that case:
- Session note → **`ai/session/YYYY-MM-DD-topic.md`** (not `notes/`).
- Durable learnings → **atomic files in `ai/memory/`** + a pointer in `ai/memory/index.md` (not `~/.claude/.../memory/`, which is the opaque, non-portable store). The in-repo `ai/` folder is the canonical, git-tracked source of truth.
- Use the atomic file format and the "posted intent" decision format from `ai/CAPTURE.md`.
If there is no `ai/CAPTURE.md`, use the defaults below (and consider running `/init-ai-workspace`).

Work through every phase. Do not skip. Reconstruct from evidence — **do not trust your recollection of a long session.**

---

## Phase 1 — Reconstruct what actually happened (evidence, not memory)
- Run `git status --short` and `git diff --stat` (and `git log` since session start) to see every file touched.
- List artifacts created/changed: scripts, prompts, docs, plans, notes, data outputs, dashboards, reports.
- Note any long-running/background work (workflows, jobs) and whether it finished and where its output landed.
Build the real inventory before writing anything.

## Phase 2 — Write/append the session note (the pick-up state is the point)
Write `notes/YYYY-MM-DD-<topic>.md` — or `ai/session/YYYY-MM-DD-<topic>.md` if the project uses `ai/` (see Project conventions) — continuing the prior note if same thread. It MUST contain:
- **What got done** — grouped by theme, with the concrete artifact each produced.
- **PICK-UP STATE** — exactly where things stand: what's complete, what's half-done, what was deliberately deferred, and **the single next action**. Be specific enough that someone else could start.
- **NEXT** — prioritized next steps with *why*.
- Findings in **prose** (numbers, verdicts, decisions) so they survive even if regenerable data is wiped.
- Links to the plan(s), backlog, reports, and memory entries.

## Phase 3 — The 6-month cold-read test (the highest-value phase)
Explicitly ask: *"If I reopened this with no memory, what would I be looking for, and what would I curse past-me for?"* Then make sure each exists:
- **A runbook** — the exact command sequence to run/resume the work, in order.
- **Auth & environment** — every key, cookie, env var, credential path, and how to refresh them. (These are almost always missing — they live in someone's head or buried in a script.)
- **Artifact layout** — where inputs/outputs live and the naming conventions.
- **Prerequisites** — what must exist/run first.
- **Gotchas learned** — the bugs you root-caused, the non-obvious behaviors, the "don't do X."
If any are missing, **write them now** (a `README`/runbook beside the code is ideal).

## Phase 4 — Durability & git audit (the one that bites)
For the key work, classify each path:
- **Committed** (portable, survives a clone) — verify with `git ls-files --error-unmatch <path>`.
- **Untracked** (filesystem-only — LOST on a fresh clone). ← the dangerous category.
- **Gitignored / local-only** (e.g. data, secrets, generated outputs) — note that it's regenerable and how.
- **In-memory** (`~/.claude/.../memory/`) — this machine only.
State plainly in the session note + runbook what is NOT safe. **If important work is untracked, recommend (and offer to make) a commit** — branch named per the ticket, honoring the repo's commit rules (e.g. no AI attribution if that's the policy). Don't commit without the human's go-ahead unless the policy says otherwise.

## Phase 5 — Memory sweep (what's worth remembering, what's now wrong)
- **New durable learnings?** If the project has `ai/memory/`, write them there as atomic files (`gotcha_`/`schema_`/`decision_`/`pattern_`/`runbook_`/`reference_`) per `ai/CAPTURE.md` + an `index.md` pointer — that is the canonical, in-repo, portable store. Otherwise capture as memory: `user` (who/preferences), `feedback` (how to work, with the why), `project` (ongoing state/decisions not derivable from code), `reference` (endpoints, keys, external pointers). Don't save what the repo/git already records.
- **Stale/wrong memory?** If this session contradicted an existing memory, fix or delete it (note when a prior memory misled you — that's a high-value correction).
- **Index — regenerate, don't hand-edit** (if `ai/memory/` is an OKF bundle): the index is generated.
  After writing/editing notes run `python <init-ai-workspace-skill-dir>/okf_normalize.py ai/memory --reindex`
  to rebuild root + per-topic `index.md` from frontmatter (durable prose above the
  `<!-- okf-index:auto -->` marker is preserved).
- **OKF conformance — run the tool, don't eyeball it** (see `ai/CAPTURE.md`): run
  `python <init-ai-workspace-skill-dir>/okf_normalize.py ai/memory` (dry-run). If it reports any
  frontmatter drift on the notes you touched (missing `type`, `updated`→`timestamp`, absent
  `description`/`tags`), re-run with `--apply`; if it reports renames, run `/init-ai-workspace`
  Phase 4 (which handles foldering + reference fixups) rather than a bare `mv`. The session is not
  "captured" until it reports 0 drift.
- **Link new notes inline** — when a new note genuinely relates to an existing one, add an inline
  markdown link between their bodies (`[other note](type_slug.md)`). That's what populates the OKF
  graph; cross-references that live only in `index.md` leave the graph disconnected.

## Phase 6 — Loose ends, caveats & decisions
- **Open bugs / deferred work** → a backlog file (`ai/plans/...-known-gaps.md` or similar) with *what / why / where / fix* per item, prioritized.
- **What's NOT trustworthy yet** — metric caveats, unverified numbers, data-integrity flags, "subset only," "needs human review." Future-you must know which results to distrust.
- **Decisions + WHY** — any choice made this session that isn't self-evident from the code. Capture the rationale, not just the outcome (a decision without its why gets re-litigated).

## Phase 7 — Sync the surfaces (stale docs lie)
- Are design docs, runbooks, dashboards, and reports consistent with what's actually true now? Regenerate generated artifacts (dashboards/rollups). Add a status banner or update to anything that now overstates/understates reality. Stale "current status" docs are worse than none.
- **Regenerate the knowledge graph** if the project ships the OKF viewer (`ai/scripts/okf-viewer/render.py` or equivalent) and you touched `ai/memory/` this session — its HTML is a generated artifact like any dashboard.

## Phase 8 — Ask the human (only they know these)
Use the question tool for the genuinely human-only inputs, e.g.:
- "Commit this session's work to git now?" (the durability close).
- "Any decision/context I should record that I'm missing?"
- "What's the actual next priority when we resume?" (your guess vs their intent can differ).
- "Anything that should NOT be acted on / is on hold?"
Keep it to what changes the handoff — don't quiz for sport.

## Phase 9 - What is the Resumption prompt?
Write a RESUME.MD in the root dir
- If I wanted to prompt myself to continue this project in the direction indicated by the human, what would I need in the prompt to refill accurate context and understand next steps with informed questions to ask the human in resumption?

## Output — the close-out summary
End with a tight report:
1. **Captured** — the files written/updated (session note, runbook, memory, backlog, synced docs).
2. **Durability verdict** — what's safe, what's untracked, the recommended commit.
3. **Resume in one line** — the single next action a returning agent should take.
4. The human-only questions (Phase 8), if any remain open.

## Anti-patterns (the ways this fails)
- A pretty summary with no **pick-up state** or **next action**.
- Documenting *what* without *how to run it* (no command sequence / auth).
- Assuming the work is safe without checking git (untracked ≠ saved).
- Writing new memory but leaving contradicted old memory in place.
- Reporting results without flagging which numbers aren't trustworthy.
- Skipping the human questions and guessing the next priority.
