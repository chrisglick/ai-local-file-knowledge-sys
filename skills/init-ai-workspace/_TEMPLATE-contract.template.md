<!-- DELETE-THIS-COMMENT-BLOCK-BEFORE-MINTING -- everything from this line down to the closing
     comment marker below is instructions for WRITING a spec, not part of the spec itself.
     `gov --lint-spec` refuses by name if it's still present (it would otherwise garble the
     path-existence guard below, since this comment's own example paths look like real
     references). Delete the whole block once you've read it.

     Copied to ai/contracts/_TEMPLATE-contract.md by /init-ai-workspace, only if the govern-work
     skill is installed. Copy THIS file to a new spec (e.g. ai/contracts/my-change.md), DELETE
     THIS HEADER COMMENT, and edit the sections below, then `gov mint ai/contracts/my-change.md`.

     gov --lint-spec / gov mint check every one of these mechanically, before anything is
     created, and refuse with a message naming the exact fix. Nothing here is a suggestion:
       - exactly one `## Goal` heading (plural `## Goals` is refused outright)
       - `## Done when` with 1-4 checkable bullets (a command, a file, a specific behavior --
         not a feeling; "it works" and "looks good" are refused as too vague to check)
       - `## Deliverables`, if present, at most 4 bullets
       - exactly one `Lane:` line
       - a `Report:` line (or `## Report` section) naming where the completion report lands
       - the verify expectation must already be real, non-placeholder prose in this project's
         CLAUDE.md `## Verify` section -- `mint` will not create a worktree pointed at a project
         that has never said how its own work gets checked
       - every backtick-quoted path this spec references (anything containing `/` or `\`) must
         already exist on disk

     A spec that is too big to fit this shape is a signal, not an obstacle: split it. A spec that
     mixes a known mechanical fix with an open-ended "find out if X is possible" should split
     along THAT line even if it would technically fit under one Goal/Deliverables count -- size
     by how many rounds of check-and-adjust the work will plausibly need, not by file count. -->

## Goal

<One sentence. The single objective this spec accomplishes. Not "and also...".>

## Done when

- <a concrete, checkable outcome -- a command that exits 0, a file that exists with specific
  content, a test that passes>
- <1-4 of these total>

## Deliverables

- <path/to/file.ext -- optional section; at most 4 entries; omit if the spec is a pure fix with
  no new files>

Lane: <one short label for the single kind of work this is, e.g. `docs`, `backend`, `frontend` --
whatever categorical split this project actually uses; the guard only requires ONE, not a
specific vocabulary>

Report: ai/contracts/reports/<spec-id>-report.md

<!-- The report path above must resolve under this repo once the builder writes it -- the
     directory does not need to exist yet (the builder creates it), but the Report: line itself
     must be present so `land` knows where to look for the `## Decisions` section it requires. -->

## Context (optional)

<Anything a builder with zero memory of this conversation needs and can't get from the repo
itself: why this work is happening, what was already tried, what NOT to do. If the answer is
"nothing, the repo says it all," delete this section -- don't pad a spec to look thorough.>

## Overrides (optional; only if you are deliberately tripping a guard)

<!-- - AllowMixedLane: <reason this genuinely needs more than one lane>
     Overrides are LOUD (printed at mint) and recorded on the contract -- an override is a
     visible, auditable exception, never a silent one. Delete this section if you have none. -->
