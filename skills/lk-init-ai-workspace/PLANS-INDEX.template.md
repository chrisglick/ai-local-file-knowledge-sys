---
file: ai/plans/INDEX.md
purpose: Every open plan, one line each, grouped into the LANES that decide what may run at the
         same time. The routing table for "what is there to do" and "what can run beside it".
         Detail lives in the plan file; current state lives in RESUME.md.
last_updated: YYYY-MM-DD
---

# Open plans, by lane

`RESUME.md` says what is happening NOW. This says what EXISTS and **what may run in parallel**.
`_DONE/` holds the finished ones.

## The lane rule

**A lane is a set of files one agent or person owns at a time.** Two pieces of work in the same
lane run one after the other; work in different lanes may run side by side. Keeping two builders
off one file is a scheduling decision made here, not something a tool refuses. If {{PROJECT}}
has only one person working at a time, one lane is fine; delete the others.

| Lane | Owns | Runs |
|---|---|---|
| **A — <core>** | <the files or dirs this lane owns> | ONE slice at a time |
| **B — <ui / content / tools>** | <files> | serial within the lane |

## Lane A — <core>

| Plan | What it is | State |
|---|---|---|
| `YYYY-MM-DD-<slug>.md` | <one line> | <open / in-flight / blocked on …> |

## Lane B — <…>

| Plan | What it is | State |
|---|---|---|
