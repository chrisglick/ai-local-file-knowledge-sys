---
status: active            # draft | active | blocked | done | abandoned
owner: human:your-handle  # one owner per plan; the person who can say "done"
ticket:                   # external id if any (issue #, Linear key, ...) — pointer, not a copy
blocked_by:               # another plan's filename, or a one-line external dependency; empty = not blocked
as_of: YYYY-MM-DD         # the date the body below was last true; /lk-end-session bumps it
---

# Plan — <one thread, one sentence>

> `ai/plans/` files are **live per-thread state documents**, not frozen specs: one thread = one
> plan = one owner. `RESUME.md` is a thin index over these (one row per plan); the detail lives
> here, never there. Copy this template to `ai/plans/<thread-slug>.md` and fill it in.

## Goal

<The single outcome this thread exists to produce. Not a list.>

## Done when

- <a checkable outcome: a command that exits 0, a file that exists, a behaviour you can show>
- <keep to 1-4 of these>

## Current state (as_of above)

<What is true right now: what's built, what's committed vs untracked, what's deployed. Replace,
don't append — the history is in `ai/session/`.>

## Next action

<One concrete step. Not a backlog.>

## Decisions made on this thread

Link, don't restate: each decision is a `decision_*.md` note in `ai/memory/` with its own
`sources` and `**Verify:**` line.

- [<decision title>](../memory/decision_<slug>.md)

## Open questions

- <a fork nobody has decided; file it as an `open-question_*.md` note when it needs a ruling>

## Landmines

- <the thing that will bite the next person: an env var that must be set, a step that fails
  silently, a file that must not be regenerated>
