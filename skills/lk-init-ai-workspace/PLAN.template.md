---
file: ai/plans/YYYY-MM-DD-<slug>.md
purpose: <one or two lines: what this plan exists to decide or build, and for whom>
status: OPEN — <dated, living one-liner: what is built, what is next, what blocks it>
opened: YYYY-MM-DD
owner: <human:<id> | the agent role that coordinates it>
lane: <optional: the set of files one builder owns at a time — see INDEX.md>
depends_on: <optional: other plan slugs, a ruling, an external event>
as_of: YYYY-MM-DD   # the date the body was last true; bumped at session close
---

# Plan: <title> — <one-line essence>

> TEMPLATE. A plan is a BROAD prose artifact: the durable record of what sparked it, the
> human's rulings, the design that emerged, and the territory still open. It is not a unit of
> work. Work is cut from it one slice at a time (a branch, a ticket, a build brief) and the
> slice ledger at the bottom records each one. A plan stays OPEN while any territory is
> unbuilt; it moves to `_DONE/` only when everything is built or deliberately abandoned.
> Blocked or parked stages stay in the plan's prose — there is no separate ledger for them.
> Prefer growing an open plan over opening a new one (see `ai/plans/README.md`).

## Trigger

The moment that started this — the playtest result, the bug, the human's words — verbatim
where possible, dated. This is the one header every plan has first.

## <choose the body headers this plan needs>

Only `## Trigger` (first) and `## Slices` (last) are fixed. For everything between, CHOOSE the
headers that fit what THIS plan is capturing: a design exploration reads differently from a bug
diagnosis or a staged program. Proven vocabulary (combine, rename, or invent as the material
demands):

- `## Status (dated)` — living audit of built vs pending; update it, don't rewrite history
- `## Why` / `## Problem` / `## Context (what broke)` — motivation, pain, diagnosis
- `## What is already true (do not rebuild)` — verified facts with file:line, dated
- `## Shape` / `## Mechanism` / `## Architecture decision` — the form the thing takes
- `## Rulings (<human>, dated)` — the human's decisions VERBATIM; binding, never re-litigated.
  Each one also becomes a `decision_` note in `ai/memory/` with this plan as its source
- `## Options (pick one)` — menus prepared for a ruling, trade-offs stated
- `## Recommendation (<agent>)` — the advisor's pick whenever a menu is offered
- `## Doctrine boundary` — where this touches standing decisions; read-first pointers
- `## Stages` / `## Phases` / `## Part A/B/C` — decomposition into future slice territory
- `## Constraints` / `## Non-goals` / `## Deliberately NOT in scope`
- `## Verify` / `## Exit criteria` — how built slices prove themselves (feeds each slice's done-when)
- `## Risks carried into every slice` — what each builder must know before touching it
- `## Open questions` / `## Still open` — what genuinely waits on the human
- `## Parked` / `## Future vision` — territory deliberately not pursued yet, with the reason
- `## Kinship` / `## Sources` — related plans, projects, vocabulary
- `## Standing debt` / `## Consequence to handle` — side-effects this plan knowingly creates

## Slices

Ledger of the work cut from this plan. Add a row when a slice starts; update it when it lands
or is abandoned. The row is the pointer; the detail lives in the slice's own branch, ticket or
brief.

| Slice | Where (branch / ticket / brief) | Status | Landed |
|---|---|---|---|
| 0 — <name> | <pointer> | planned / in-flight / LANDED / abandoned / optional | <commit or date> |
