# govern-work — design rationale (R-numbered rulings)

The *why* behind the mechanics in `SKILL.md`. Read this before changing guard behavior, arguing
with a refusal, or explaining the system's protections to someone else.

## Deny-list, not allow-list (R4 / R3 — why edits get refused, and why there's no file whitelist)

A small number of files in a governed project are **the referee** — the scripts that decide
whether a piece of work passes or fails (`ai/scripts/gov`, `ai/scripts/okf`, the ratchet baseline
file). If an agent working under a contract could edit those, a failing check could be made to
pass by changing the check instead of fixing the work, and a reviewer skimming the diff might not
notice. So those specific paths are refused outright by a git `pre-commit` hook — exact-match
only, never a glob or a directory prefix, so it can never accidentally widen into a general rule
about which files an agent may touch. Editing one of them for real needs the literal path named in
the spec **and** an explicit, loudly bannered `--allow-enforcement-edit` — an override is a
visible, auditable exception, never a silent one.

**Why there's no allow-list of files an agent may touch.** An earlier version of this kind of
system tried the opposite: give each unit of work an explicit whitelist of files it was allowed to
change, and refuse anything else. It made the work worse, not safer — an agent that genuinely
needed a file outside its list would contort the change to fit inside the list instead, piling
logic into whatever file it could reach; that's the god-object problem with a tool enforcing it.
The fix wasn't a smarter whitelist; it was recognizing that an isolated workspace — its own branch,
its own worktree — is already the boundary that matters. `mint`'s declared-path overlap check is
what a whitelist was actually good for: a **non-fatal warning** that two pieces of work are about
to collide on the same file, so the orchestrator doesn't dispatch them at the same time. It is a
sequencing signal, not a gate on the builder.

## Quote the ruling, don't paraphrase it (R7 — the anti-re-adjudication mechanism)

`gov --rule` records a human's decision in their **own words**, dated, never a summary. An agent
revisiting the topic later will readily argue with a paraphrase — "the team decided X was
better" is already an interpretation, and interpretations invite re-interpretation. A direct
quote is much harder to relitigate: there's nothing to reinterpret, only something to honor or
explicitly ask to reopen. `gov --rule` refuses an empty ruling and refuses text that reads as a
paraphrase of a decision rather than the decision itself.

## Agent rights (R10 — advisory-strength, printed in full at every `mint`)

The contract is bi-directional. A contracted agent has these rights, same advisory strength as
every guard in this system — prose and small mechanics, not hashed field data:

1. **A self-contained brief.** Everything needed to start a contract is in its onboarding file
   (`CONTRACT-ONBOARDING.md`, written into the worktree at `mint`): the spec verbatim, the one
   verify command, the report path, and this rights block. A builder should never need context
   from outside that file to begin.
2. **Verify before you are judged.** `gov verify` is a dry-run gate — run it as many times as you
   want, at any point. You are never graded against a check you could not first run yourself.
3. **The right to say "underspecified," not fabricate confidence.** If a brief genuinely doesn't
   give you enough to proceed honestly, `gov abort --underspecified --reason "<gap>"` is a valid,
   honored **outcome**, not a failure. It keeps your branch, files one `type: open-question` note
   per named gap, and is recorded as `refused-underspecified` — a distinct, legitimate status, not
   a failure code.
4. **The right to challenge, in the ledger, never in the diff.** You may never silently ignore or
   re-argue a standing decision note. You may always file an open question (`gov --open`) that
   cites the decision note's id and states the new evidence. That is the whole difference between
   re-adjudication (forbidden) and honest clarification (always allowed).
5. **The right to be heard past your own contract.** Your report's optional `## For the next
   agent` section is read by the orchestrator at `land`, not discarded. Items it agrees with
   become durable `ai/memory/` notes; the rest still ships inside the persisted report. Abstaining
   is fine — write `none`.

## The honesty note (R8 — read this before trusting any of this)

**These guards are advisory-strength, not airtight, and that is stated on purpose.** Nothing here
can actually stop an agent that has a shell and file access: it can bypass a check tool
(`git commit --no-verify`), skip a hook, or edit a guard file directly if it chooses to. What the
tooling does is raise the default cost of doing the wrong thing above zero, and make the wrong
thing visible and refusable by default — moving the baseline from "works only if everyone
remembers the discipline" to "works unless someone deliberately overrides it." Actually preventing
every bypass would need running agents in a sandbox with no such access at all, which is a
different, heavier system than this one, and out of scope here. Say this plainly rather than
implying more protection than exists — the existing knowledge-system README is scrupulously honest
about its own limits; this skill matches that register, not a stronger one.
