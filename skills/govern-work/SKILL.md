---
name: govern-work
description: >
  Enforcement layer + contract runner for the in-repo knowledge system: a deny-list guard,
  a drift detector, a ratchet, and a mint/verify/land/abort contract runner over git
  worktrees, so documented discipline (writing decisions down, sizing work sanely, gating
  merges on a completion report) becomes a mechanical default instead of something an agent
  has to remember to do mid-work. USE WHEN: "govern this repo", "gate the merge", "mint a
  contract", "run gov", "check for drift", "/govern-work", "set up the ratchet", "enforce the
  deny-list", "land this work", or any request to bound/isolate/verify agent build work
  against a spec.
---

# govern-work — the enforcement layer

`init-ai-workspace` / `backfill-memory` / `end-session` are a **capture** system: they record
knowledge after the fact and say plainly, in their own docs, that nothing forces the recording
to happen. `govern-work` is the fourth skill — it supplies the piece the other three admit they
lack: mechanisms that gate on the ledger instead of merely asking an agent to keep it.

**The one-line thesis:** the enforcement that works constrains the transaction, not the agent.
Deny-list the referee, gate the close, refuse the oversized or underspecified spec. A tool that
tries to constrain an agent's *reach* mid-work (a whitelist of files it may touch) makes the
output worse — see "Why there's no allow-list of files" below; that lesson is load-bearing, not
decoration.

Two engines ship in this skill directory, reached through one shim:

- **`govern.py`** — the standalone verbs: `--open`, `--rule`, `--lint-spec`, `--ratchet`,
  `--baseline`, `--drift`, `--gate`. Useful with zero contract machinery at all.
- **`govern_contract.py`** — the contract runner: `mint` / `verify` / `land` / `abort`, over
  real `git worktree`s. Imported by `govern.py`; both ship together, invoked the same way.

A project carries only a ~10-line shim, `ai/scripts/gov` (installed by `init-ai-workspace`, see
below) — the engine lives once in this skill directory, same shape as `ai/scripts/okf`.

## Every verb

| Verb | Does |
|---|---|
| `gov --open "<question>"` | File a `type: open-question` note in `ai/memory/` — a fork nobody has decided yet. |
| `gov --rule <note> --verbatim "<text>"` | Close an open-question note into a `type: decision` note carrying the human's ruling **word for word**, dated. Refuses an empty or paraphrased-looking ruling. |
| `gov --lint-spec <file>` | The sizing + underspecification guards, standalone — usable before any contract exists. |
| `gov --ratchet` | Exit 1 if any tracked count (unverified notes, configured grep rules) rose above its committed baseline. Never asserts a count is zero — only that it didn't get worse. |
| `gov --baseline` | Rewrite the baseline file, **downward only.** Refuses to raise any tracked count. |
| `gov --drift [bundle]` | Read the distilled session corpus, surface decision-shaped human turns with no matching decision note. The flagship feature — see "The drift judgement pass" below. |
| `gov --gate` | Composite: `okf --gate` + `gov --drift` + `gov --ratchet`. What a Stop hook calls (`hooks/stop-gate.sh`). |
| `gov mint <spec>` | Run the sizing guards, spin an isolated worktree, install the deny-list hook, print a self-contained builder onboarding. |
| `gov verify --id <id>` | Run the ONE blessed verify command, parsed live from the project's own `CLAUDE.md`. A dry-run — callable any number of times, never a grading event by itself. |
| `gov land --id <id>` | Rebase onto base, check the diff against the deny-list, run `verify`, refuse without a report containing a `## Decisions` section, merge fast-forward-only on green. |
| `gov abort --id <id>` | Remove the worktree, keep the branch. `--underspecified --reason "<gap>"` is a valid, honored outcome — see rights below. |

Every refusal names the exact fix. A tool that refuses silently, or refuses without saying what
would make it pass, teaches people to route around it instead of listening to it.

## The contract lifecycle

```
gov --lint-spec spec.md      # optional standalone check before minting
gov mint spec.md             # sizing + underspec guards, worktree, hook, onboarding
  ... builder works in the worktree, reads CONTRACT-ONBOARDING.md first ...
gov verify --id <id>         # dry-run, from the main repo, any number of times
gov land --id <id>           # rebase, deny-list check, verify, ledger gate, merge ff-only
    -- or --
gov abort --id <id> [--underspecified --reason "<gap>"]
```

A spec that mixes a mechanical fix with an open-ended investigation should be split along that
line, not by file count. Size a spec by **how many times the work will plausibly need checking**
before it's right, not by how many files or deliverables it names. A spec that names five files
but is really "make the one obvious fix, confirm it, done" is smaller than a spec that names one
file but needs ten rounds of try-check-adjust. Mixing shapes in one spec — bundling a
known-mechanical change with an open-ended "investigate this" — is the wrong-sized contract even
when every individual guard passes.

## The drift agent-judgement pass (sealed ruling — read this before running `--drift`)

`gov --drift` is a **heuristic engine**, not a decision-maker. It reads the distilled session
corpus (`ai/session/raw/*.md` or `ai/sessions/raw/*.md`, whichever a project already uses) and
flags human turns that read as decision-shaped — imperative phrasing, ruling language, "we
decided," "from now on," a correction — that have no matching `type: decision` note. It is
**deliberately recall-favoring**: it would rather show you ten candidates and let nine be noise
than miss the one real drift.

**The sealed ruling on who does the judgement:** the heuristic engine surfaces candidates; **the
running agent does the judgement pass.** `--drift`'s job stops at "here is a first-pass net,
expect noise" — it does not, and should not, decide which candidates are real rulings worth a
`decision` note. When you run `gov --drift`, read every candidate it prints, and for each one:

- If it's a genuine standing ruling with no note yet, capture it — either `gov --rule` against an
  existing `gov --open` note, or write the `decision` note directly if none was ever filed.
- If it's just prose that happens to contain ruling-shaped words (a status report saying
  "sealed," a quote inside a quote, a hypothetical), leave it — don't manufacture a decision note
  for something that was never actually decided.

Never treat the raw candidate list as "these are all real decisions." That misreads what the
tool is for and will pollute `ai/memory/` with notes nobody actually ruled on.

`--drift` degrades honestly, never silently, on day zero: no corpus at all, a `local`-mode corpus
that exists on the operator's machine but not on a fresh clone (gitignored by design — see the
knowledge-system README), or a corpus with nothing newer than the last decision. Every case
prints which one it is and names the fix, never a bare empty result presented as "all clean."

## Deny-list, not allow-list (R4 / R3 — why edits get refused, and why there's no file whitelist)

A small number of files in a governed project are **the referee** — the scripts that decide
whether a piece of work passes or fails (`ai/scripts/gov`, `ai/scripts/okf`, the ratchet baseline
file). If an agent working under a contract could edit those, a failing check could be made to
pass by changing the check instead of fixing the work, and a reviewer skimming the diff might not
notice. So those specific paths are refused outright by a git `pre-commit` hook — exact-match
only, never a glob or a directory prefix, so it can never accidentally widen into a general rule
about which files an agent may touch. Editing one of them for real needs the literal path named in
the spec **and** an explicit, loudly banered `--allow-enforcement-edit` — an override is a visible,
auditable exception, never a silent one.

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

## Sizing a spec by verify-iterations, never by deliverable count

The finding that matters, from real dispatch history: the failure mode was not small slices but
**wrong slices** — research-class work (an outcome that may legitimately be "doesn't work") gating
a pipeline-class wave whose own outcome was never in doubt. A spec whose shape mixes "run the
known fix and confirm it" with "find out whether X is even possible" should split along that seam.
`gov --lint-spec` enforces the mechanical half of this (exactly one `## Goal`, a `## Done when`
with 1–4 checkable bullets, `## Deliverables` capped at 4, one declared `Lane:`) — the subjective
half (does this spec actually mix two shapes) is a judgement call for whoever mints it.

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

## Day zero (a fresh adopter's first week)

Every verb degrades with an explanation, never an empty result, on a repo that has nothing: no
`CLAUDE.md`, no verify command, no session history, no baseline. `--drift` with no corpus says
why and names the fix. `--ratchet` with no baseline offers to write one from current counts (via
`--baseline`). `mint` refuses without a `govern_verify_command` configured in `ai/okf.conf`, and
the refusal message says exactly what to add and why one blessed command matters more than any
other single addition. A fresh adopter's first week is realistically `--lint-spec` + the contract
runner + the ledger gate at `land` — `--drift` and `--ratchet` earn their keep as session and note
history accrue; don't judge either on day one.

## Config

Flat `govern_`-prefixed keys in `ai/okf.conf` (this file has no `[section]` syntax anywhere; the
existing knowledge-system config is `key = value` lines, and consistency wins over inventing one):

| Key | Used by |
|---|---|
| `govern_verify_command` | `mint` / `verify` — the ONE blessed command. `mint` refuses without it. |
| `govern_verify_trivially_true` | `true` for a docs/research repo with no test suite. Loud one-time banner at mint; recorded on the contract. Correctness stays unverified there — the ledger gate and deny-list still bind. |
| `govern_base_branch` | `mint` — default `main`. |
| `govern_worktree_dir` | `mint` — default `../<repo>-contracts`. |
| `govern_ratchet_baseline` | `--ratchet` / `--baseline` — default `ai/govern-baseline.json`. |
| `govern_ratchet_grep_<name>` | an extra `--ratchet`-tracked regex count, named `<name>`. |

`init-ai-workspace` scaffolds these into `ai/okf.conf` as commented-out lines with the same
teaching tone as the existing `archive =` block — see its `okf.conf.template`.

## Install

`init-ai-workspace` scaffolds `govern-work` into a project (idempotent, marker-gated, same
mechanism as everything else it writes) — see that skill's `SKILL.md` for the phase. If you're
wiring it by hand: copy `gov.shim.sh` to `ai/scripts/gov` in the target project and `chmod +x`
it; the shim resolves the engine at `~/.claude/skills/govern-work/` (override with
`GOV_SKILL_DIR`). `pyyaml` is the only runtime dependency, same as `okf_normalize.py`.

Run the test suite (needs `pip install pytest`):

```bash
cd ~/.claude/skills/govern-work && python -m pytest -q
```

## Hooks

- `hooks/pre-commit` — the deny-list guard. Installed into a contract worktree's shared hook dir
  by `mint`. Inert outside a contract (detected by a marker file in `TMPDIR`, never in the repo —
  so nothing a contracted agent can stage or commit spoofs or erases the activation signal).
- `hooks/stop-gate.sh` — the Stop hook this skill supplies (the knowledge-system README says
  plainly that no Stop hook ships there — this is that hook). Calls `ai/scripts/gov --gate`.
  Degrades to exit 0 with a one-line note on every infra-absence case (no git repo, no shim, no
  working python) — it never wedges a session on missing tooling, but it does surface a real
  `--gate` failure once the shim actually runs.

Neither hook is auto-wired into Claude Code's own hook config by this skill — `mint` installs
`pre-commit` per contract; wiring `stop-gate.sh` into `settings.json`'s `hooks.Stop` is a project
choice (the `update-config` skill can do this).
