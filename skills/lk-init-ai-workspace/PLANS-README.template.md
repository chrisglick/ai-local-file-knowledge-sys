# Plans

A plan is the durable record of an idea, from the moment that sparked it through rulings,
design, slices of work, and close-out. This folder is the backlog for {{PROJECT}}.

## Lifecycle

```
playtest / bug / conversation  →  plan written  →  slices cut  →  slices land  →  plan closed
```

1. **Something surfaces** in use, in a bug, or in conversation. The human names it, or the agent
   spots it.
2. **A plan captures it**: trigger, shape, rulings, open questions, how it will be verified.
   Start from `_TEMPLATE-plan.md`.
3. **Slices are cut from the plan** one at a time (a branch, a ticket, a build brief). The plan's
   `## Slices` table is the ledger. The plan stays open while any territory is unbuilt.
4. **When every slice is landed or deliberately abandoned**, the plan moves to `_DONE/`.

## The one rule: finish before starting

**Prefer closing an open plan over opening a new one.** A new plan is easy to write and hard to
finish. Before opening one, check whether the work belongs inside an existing plan, even if the
fit isn't perfect. A plan that grows a stage is better than two plans that split attention.

`INDEX.md` routes the open plans so a coordinator can see what's live and what can run beside
it. A plan that isn't in the index isn't scheduled.

## When a plan is done

1. Set the plan's front-matter `status:` to CLOSED with the date and the reason (built / abandoned).
2. Move the file to `_DONE/`.
3. Remove or strike its row in `INDEX.md`.

A plan in `_DONE/` is history: it explains WHY something was built, which is what someone asks
months later. `RESUME.md` at the repo root is a thin table over the open plans; the detail lives
here, never there.

## Folder contents

| Path | What it is |
|---|---|
| `INDEX.md` | The routing table: every open plan, one line each, grouped by lane |
| `_TEMPLATE-plan.md` | Starting point for a new plan |
| `_DONE/` | Closed plans (the archive) |
| `*.md` | Open plans, named `YYYY-MM-DD-<slug>.md` |
