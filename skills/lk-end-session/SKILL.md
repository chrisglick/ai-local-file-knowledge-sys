---
version: 1.0.0
name: lk-end-session
description: >
  Structured session close-out that captures the full scope of a working session so it
  survives the three ways context dies: the conversation ending, single-machine state, and
  a fresh git clone. Runs a fixed pipeline — reconstruct what happened, write the pick-up
  state, run the 6-month cold-read test, audit git/durability, sweep memory, log loose ends,
  sync docs/dashboards, and ask the human the things only they know.
  USE WHEN: ending a work session, "close the session", "wrap up", "end session", "/lk-end-session",
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
If there is no `ai/CAPTURE.md`, use the defaults below (and consider running `/lk-init-ai-workspace`).

Work through every phase, reconstructing from evidence — a long session's recollection drifts.

---

## Phase 0 — Archive the transcript (FIRST; it's the citation target)
Everything below distills this session into prose, and **you cannot cite yourself as the source** —
archive the conversation before distilling it, and before Claude Code's retention window deletes
it. Archive modes, the md/jsonl split, secret-scan limits, and public-repo rules:
[`../lk-reference/transcript-safety.md`](../lk-reference/transcript-safety.md).

```bash
ai/scripts/okf --distill --out ai/<session-dir>/raw/$CLAUDE_CODE_SESSION_ID.md \
                         --raw ai/<session-dir>/raw/
```
(No shim? `python <lk-init-ai-workspace-skill-dir>/distill_transcript.py --out ... --raw ...`)

- **Cite it from every note you write below**: a decision's `sources` entry is
  `ai/<session-dir>/raw/<id>.md`, never `session 2026-07-15` — a prose source can't be opened, so
  the claim can never be re-checked (`--check` warns on these).
- **Read the secret-scan line: `0 hits` means "nothing obvious", never "safe to publish".**
- Re-run this at the very end if the session continued — the copy is a snapshot and `cp` overwrites.
- Transcript already gone (older than `cleanupPeriodDays`, or a non-Claude-Code surface)? Say
  "source unavailable" plainly in the session note — an honest gap beats an invented citation.

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

## Phase 2.1 — Update the plan file(s) this session's thread(s) own (the live state)
If the project uses the plan-as-thread convention (`ai/plans/*` with `status`/`as_of`
frontmatter — see `PLAN.template.md` in the lk-init-ai-workspace skill), the plan file is the
**live state document** for its thread, and this session must leave it true:
- Update its **Current state** and **Next actions** sections to match reality *now*.
- Bump `as_of` to today; set `status` honestly (`active` / `blocked` + `blocked_by` tickets /
  `done` / `parked`). A plan left saying "NEXT — Phase 2" when Phase 6 is current is exactly
  the rot this system exists to prevent.
- **Release the claim.** Clear the plan's `claimed:` field — the session is over, so no agent is
  actively working the thread; a lingering claim blocks the next worker for 24h for nothing.
  (Ownership — `owner:` — persists; the claim never does.) If you never set `claimed:` when work
  started, say so in the close-out: the claim discipline only protects threads when every
  session honors it.
- **Done criteria**: check off any `DC-n` completed this session **with the probe's evidence
  quoted** (in Current state or the session note). Evidence-free checkmarks are how a plan lies
  with a straight face. Never renumber criteria; drops get tombstones.
- **Mirror to the tracker** if `ticket:` is set and a tracker MCP is available: the ticket's
  state/comment should reflect the plan's status change (offer it; don't silently push).
- New thread started this session with no plan file? Create one from `PLAN.template.md` — a
  thread without a plan file has no home for its state, and its detail will end up fattening
  RESUME or orphaned in a side file.
- The session note (Phase 2) records *what happened today*; the plan records *where the thread
  stands*. Don't duplicate — link.

## Phase 3 — The 6-month cold-read test (the highest-value phase)
Explicitly ask: *"If I reopened this with no memory, what would I be looking for, and what would I curse past-me for?"* Then make sure each exists:
- **A runbook** — the exact command sequence to run/resume the work, in order.
- **Auth & environment** — **where** each key/cookie/env var lives and **how to refresh it**, never
  the value. Write `AWS creds: ~/.aws/credentials [default] — refresh with aws sso login`, never the
  key itself. These pointers are almost always missing (they live in someone's head or buried in a
  script), which is why the temptation is to paste the real thing — don't: a runbook is committed,
  and a secret in git history must be rotated, not removed.
- **Artifact layout** — where inputs/outputs live and the naming conventions.
- **Prerequisites** — what must exist/run first.
- **Gotchas learned** — the bugs you root-caused, the non-obvious behaviors, the "don't do X."
If any are missing, **write them now** (a `README`/runbook beside the code is ideal).

## Phase 4 — Durability & git audit (the one that bites)
For the key work, classify each path:
- **Committed** (portable, survives a clone).
- **Untracked** (filesystem-only — LOST on a fresh clone). ← the dangerous category.
- **Gitignored / local-only** (e.g. data, secrets, generated outputs) — note that it's regenerable and how.
- **In-memory** (`~/.claude/.../memory/`) — this machine only.
State plainly in the session note + runbook what is NOT safe. **If important work is untracked, recommend (and offer to make) a commit** — branch named per the ticket, honoring the repo's commit rules (e.g. no AI attribution if that's the policy). Don't commit without the human's go-ahead unless the policy says otherwise.

## Phase 5 — Memory sweep (what's worth remembering, what's now wrong)
- **New durable learnings?** If the project has `ai/memory/`, write them there as atomic files (`gotcha_`/`correction_`/`schema_`/`decision_`/`pattern_`/`runbook_`/`reference_`) per `ai/CAPTURE.md` + an `index.md` pointer — that is the canonical, in-repo, portable store. Otherwise capture as memory: `user` (who/preferences), `feedback` (how to work, with the why), `project` (ongoing state/decisions not derivable from code), `reference` (endpoints, keys, external pointers). Don't save what the repo/git already records.
- **Stale/wrong memory?** If this session contradicted an existing memory, fix or delete it (note when a prior memory misled you — that's a high-value correction).
- **Corrections you already caught?** If the human explicitly corrected a factual claim this
  session, write the `correction_` note now (`**Wrong:** / **Right:** / **Why tempting:** /
  **Risk:**`). A transcript scan is not sufficient coverage — you believed the wrong claim when
  you made it, and silent corrections leave nothing to grep for; Phase 8's direct question is the
  real net.
- **Index — regenerate, don't hand-edit** (if `ai/memory/` is an OKF bundle): after writing/editing
  notes run `python <lk-init-ai-workspace-skill-dir>/okf_normalize.py ai/memory --reindex` to rebuild
  root + per-topic `index.md` from frontmatter (durable prose above the `<!-- okf-index:auto -->`
  marker is preserved).
- **OKF conformance — run the tool, don't eyeball it** (see `ai/CAPTURE.md`): run
  `python <lk-init-ai-workspace-skill-dir>/okf_normalize.py ai/memory` (dry-run). If it reports
  frontmatter drift on the notes you touched, re-run with `--apply`; if it reports renames, run
  `/lk-init-ai-workspace`'s conformance pass (which handles foldering + reference fixups) rather than
  a bare `mv`. The session is captured when it reports 0 drift. Notes you write land
  `status: draft` with `generated.by` naming the agent (e.g. `claude-code/<model-id>`); a human
  promotes them later with `okf --promote` — never set `stable` or a `verified` entry yourself.
- **System health in ONE line — do NOT run a full audit here.** Run
  `python <lk-doctor-skill-dir>/lk_doctor.py --project .` and print only its summary line (e.g.
  *"lk-doctor: 2 WARN — draft queue 31 (>25); consider `/lk-audit-knowledge`"*). This is deliberate:
  handing someone forty unrelated findings as they try to leave is how you train them to stop
  running `/lk-end-session`, which is the phase that carries the correction question (Phase 8) and
  the durability audit (Phase 4). `/lk-audit-knowledge` is where findings get worked, in a session
  of their own.
- **Link new notes inline** — when a new note genuinely relates to an existing one, add an inline
  markdown link between their bodies (`[other note](type_slug.md)`). That's what populates the OKF
  graph; cross-references that live only in `index.md` leave the graph disconnected.

## Phase 6 — Loose ends, caveats & decisions
- **Open bugs / deferred work** → a backlog file (`ai/plans/...-known-gaps.md` or similar) with *what / why / where / fix* per item, prioritized.
- **What's NOT trustworthy yet** — metric caveats, unverified numbers, data-integrity flags, "subset only," "needs human review." Future-you must know which results to distrust.
- **Decisions + WHY** — any choice made this session that isn't self-evident from the code. Capture the rationale, not just the outcome (a decision without its why gets re-litigated — and the *why* usually lives in the assistant turns, which is what the Phase 0 archive preserves).

## Phase 7 — Sync the surfaces (stale docs lie)
- Are design docs, runbooks, dashboards, reports, and `ai/SYSTEMS.md` consistent with what's actually true now? Regenerate generated artifacts (dashboards/rollups). Add a status banner or update to anything that now overstates/understates reality. Stale "current status" docs are worse than none.
- **Regenerate the knowledge graph** if the project ships the OKF viewer (`ai/scripts/okf --render` or equivalent) and you touched `ai/memory/` this session — its HTML is a generated artifact like any dashboard.

## Phase 8 — Ask the human (only they know these)
Use the question tool for the genuinely human-only inputs, e.g.:
- **"Did I state anything factually wrong this session — including things you fixed yourself or
  let slide?"** Ask this one every time — corrections that were never voiced (quietly edited out
  of a draft, noticed and not mentioned) leave no trace to scan for. Each answer becomes a
  `correction_` note (Phase 5 format); otherwise the claim dies with the conversation and the
  next session asserts it again, confidently.
- "Commit this session's work to git now?" (the durability close).
- "Any decision/context I should record that I'm missing?"
- "What's the actual next priority when we resume?" (your guess vs their intent can differ).
- "Anything that should NOT be acted on / is on hold?"
Keep it to what changes the handoff — don't quiz for sport.

## Phase 9 — Regenerate `RESUME.md` (the resumption packet)
Rewrite root `RESUME.md` as the **thin thread index**: one row per thread → its plan file,
regenerated from plan frontmatter (detail lives in the plans, never here). It must give a future
agent enough to refill accurate context — the direction the human indicated in Phase 8, the single
next action, and the informed questions to ask on resumption.

## Output — the close-out summary
End with a tight report:
1. **Captured** — the files written/updated (session note, plan updates, runbook, memory, backlog, synced docs, RESUME.md).
2. **Durability verdict** — what's safe, what's untracked, the recommended commit.
3. **Resume in one line** — the single next action a returning agent should take.
4. The human-only questions (Phase 8), if any remain open.
