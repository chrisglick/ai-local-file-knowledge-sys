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

`init-ai-workspace` / `backfill-memory` / `end-session` are a **capture** system; nothing in
them forces the recording to happen. `govern-work` is the fourth skill — mechanisms that gate
on the ledger instead of merely asking an agent to keep it. **The one-line thesis:** the
enforcement that works constrains the *transaction*, not the agent — deny-list the referee,
gate the close, refuse the oversized or underspecified spec.

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
| `gov abort --id <id>` | Remove the worktree, keep the branch. `--underspecified --reason "<gap>"` is a valid, honored outcome, not a failure. |

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

**Sizing:** size a spec by **how many verify-iterations the work will plausibly need** before
it's right — never by file or deliverable count. A spec that names five files but is really
"make the one obvious fix, confirm it" is smaller than one file needing ten rounds of
try-check-adjust. And never mix shapes: a known-mechanical fix bundled with an open-ended
"investigate this" is the wrong-sized contract even when every guard passes (the observed
failure mode from real dispatch history was exactly research-class work — where "doesn't work"
is a legitimate outcome — gating a pipeline-class wave whose outcome was never in doubt; split
along that seam). `gov --lint-spec` enforces the mechanical half (exactly one `## Goal`, a
`## Done when` with 1–4 checkable bullets, `## Deliverables` capped at 4, one declared `Lane:`);
the shape judgement is on whoever mints.

## The drift agent-judgement pass (sealed ruling — read this before running `--drift`)

`gov --drift` is a **heuristic engine**, not a decision-maker. It reads the distilled session
corpus (`ai/session/raw/*.md` or `ai/sessions/raw/*.md`, whichever a project already uses) and
flags human turns that read as decision-shaped — imperative phrasing, ruling language, "we
decided," "from now on," a correction — that have no matching `type: decision` note. It is
**deliberately recall-favoring**: it would rather show you ten candidates and let nine be noise
than miss the one real drift.

**The sealed ruling on who does the judgement:** the heuristic engine surfaces candidates; **the
running agent does the judgement pass.** Read every candidate it prints, and for each one:

- If it's a genuine standing ruling with no note yet, capture it — either `gov --rule` against an
  existing `gov --open` note, or write the `decision` note directly if none was ever filed.
- If it's just prose that happens to contain ruling-shaped words (a status report saying
  "sealed," a quote inside a quote, a hypothetical), leave it — don't manufacture a decision note
  for something that was never actually decided; that pollutes `ai/memory/` with notes nobody
  ruled on.

`--drift` degrades honestly, never silently, on day zero: no corpus at all, a `local`-mode corpus
that exists on the operator's machine but not on a fresh clone (gitignored by design), or a corpus
with nothing newer than the last decision. Every case prints which one it is and names the fix.

## Design rationale (load on demand)

The *why* behind the guards lives in
[`reference/design-rationale.md`](reference/design-rationale.md): the deny-list/no-allow-list
history (R3/R4), quote-don't-paraphrase (R7), the honesty note on advisory strength (R8), and
the full agent-rights text (R10 — printed verbatim into every `CONTRACT-ONBOARDING.md` at
`mint`, so a builder never needs this file for it). Read it before changing guard behavior or
explaining why a refusal exists. The operational facts: enforcement files (`ai/scripts/gov`,
`ai/scripts/okf`, the ratchet baseline) are refused by the contract `pre-commit` hook unless the
spec names the literal path AND `--allow-enforcement-edit` is passed; abort-as-underspecified is
an honored outcome; challenges to standing decisions go through `gov --open`, never the diff.

## Day zero (a fresh adopter's first week)

Every verb degrades with an explanation, never an empty result, on a repo that has nothing:
`--drift` with no corpus says why and names the fix; `--ratchet` with no baseline offers to write
one (via `--baseline`); `mint` refuses without a `govern_verify_command` in `ai/okf.conf` and
says exactly what to add. A fresh adopter's first week is realistically `--lint-spec` + the
contract runner + the ledger gate at `land` — `--drift` and `--ratchet` earn their keep as
session and note history accrue; don't judge either on day one.

## Config

Flat `govern_`-prefixed keys in `ai/okf.conf` (`key = value` lines, no `[section]` syntax —
consistency with the existing knowledge-system config):

| Key | Used by |
|---|---|
| `govern_verify_command` | `mint` / `verify` — the ONE blessed command. `mint` refuses without it. |
| `govern_verify_trivially_true` | `true` for a docs/research repo with no test suite. Loud one-time banner at mint; recorded on the contract. Correctness stays unverified there — the ledger gate and deny-list still bind. |
| `govern_base_branch` | `mint` — default `main`. |
| `govern_worktree_dir` | `mint` — default `../<repo>-contracts`. |
| `govern_ratchet_baseline` | `--ratchet` / `--baseline` — default `ai/govern-baseline.json`. |
| `govern_ratchet_grep_<name>` | an extra `--ratchet`-tracked regex count, named `<name>`. |

`init-ai-workspace` scaffolds these into `ai/okf.conf` as commented-out lines — see its
`okf.conf.template`.

## Install

`init-ai-workspace` scaffolds `govern-work` into a project (idempotent, marker-gated) — see that
skill's `reference/govern-scaffold.md`. By hand: copy `gov.shim.sh` to `ai/scripts/gov` in the
target project and `chmod +x` it; the shim resolves the engine at `~/.claude/skills/govern-work/`
(override with `GOV_SKILL_DIR`). `pyyaml` is the only runtime dependency.

Run the test suite (needs `pip install pytest`):

```bash
cd ~/.claude/skills/govern-work && python -m pytest -q
```

## Hooks

- `hooks/pre-commit` — the deny-list guard. Installed into a contract worktree's shared hook dir
  by `mint`. Inert outside a contract (detected by a marker file in `TMPDIR`, never in the repo —
  so nothing a contracted agent can stage or commit spoofs or erases the activation signal).
- `hooks/stop-gate.sh` — the Stop hook this skill supplies. Calls `ai/scripts/gov --gate`.
  Degrades to exit 0 with a one-line note on every infra-absence case (no git repo, no shim, no
  working python) — it never wedges a session on missing tooling, but it does surface a real
  `--gate` failure once the shim actually runs.

Neither hook is auto-wired into Claude Code's own hook config by this skill — `mint` installs
`pre-commit` per contract; wiring `stop-gate.sh` into `settings.json`'s `hooks.Stop` is a project
choice (the `update-config` skill can do this).
