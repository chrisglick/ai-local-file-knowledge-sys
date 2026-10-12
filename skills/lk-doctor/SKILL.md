---
name: lk-doctor
version: 1.0.0
description: >
  Health check for the lk knowledge system. Checks that every lk- skill is installed, matches
  the repo clone, has no leftover pre-rename copies beside it, and that this project's ai/ wiring
  (the okf shim, ai/okf.conf, bundle vocabulary) is sound. Prints PASS/WARN/FAIL per check with a
  one-line fix, and fixes the safe parts on request (sync from the repo, remove legacy copies,
  repoint an old okf shim). Fixes are dry runs by default.
  USE WHEN: "lk doctor", "check the knowledge system", "is lk installed right", "which skill
  checks the ai system", "/lk-doctor", after upgrading the skills, after cloning a project that
  uses ai/, or when a shim fails with "engine not found".
---

# lk-doctor: is the knowledge system installed and wired right?

The lk system is five skills (`lk-init-ai-workspace`, `lk-backfill-memory`, `lk-end-session`,
`lk-audit-knowledge`, `lk-doctor`) and a shared `lk-reference` dir, copied into `~/.claude/skills`,
plus per-project wiring (`ai/scripts/okf`, `ai/okf.conf`, the `ai/memory` bundle). Copies drift from
the clone, a rename leaves the old copies behind, docs name skills that do not exist, and nothing
tells you. This is the one command that checks all of it.

## Run it

```bash
python ~/.claude/skills/lk-doctor/lk_doctor.py                     # install checks, plus project checks if cwd has ai/
python ~/.claude/skills/lk-doctor/lk_doctor.py --repo <lk clone>   # also compare the install with your clone
python ~/.claude/skills/lk-doctor/lk_doctor.py --project <dir>     # check a project other than cwd
python ~/.claude/skills/lk-doctor/lk_doctor.py --json              # the same checks, machine-readable
```

Where it looks: the skills dir is `--skills-dir`, else `$CLAUDE_SKILLS_DIR`, else `~/.claude/skills`.
The repo clone is `--repo`, else `$LK_REPO_DIR`, else drift checks are skipped (one WARN says how to
turn them on). The project is `--project`, else the cwd if it has `ai/memory` or `ai/okf.conf`, else
project checks are skipped (one INFO line).

Output is one line per check: `PASS`, `WARN`, `FAIL`, or `INFO` for a note that needs no action.
Every WARN and FAIL has a `fix:` line under it, and a summary line comes last. Exit 0 with no FAIL,
1 with any FAIL, 2 on a usage error.

**When an agent runs this skill:** run the command, report FAILs first and then WARNs, and offer
the fix verbs below. Never pass `--yes` without the user's go-ahead.

## What it checks

| Level | Check | Reports when | Fix |
|---|---|---|---|
| install | lk skills present | `lk-init-ai-workspace` or `lk-end-session` missing (FAIL); any other lk skill missing, or a SKILL.md without `version:` (WARN) | `--sync-from` |
| install | legacy copies | unprefixed pre-rename copies (`init-ai-workspace`, `backfill-memory`, `end-session`, `reference`) still installed | `--remove-legacy` |
| install | drift vs repo | installed `version:` or any file's sha256 differs from the clone (caches ignored); a legacy copy is compared with its lk- counterpart | `--sync-from` |
| install | normalizer standard | `OKF_STANDARD_VERSION` in `lk-init-ai-workspace/okf_normalize.py` is not 0.2 (WARN), or the file is missing (FAIL) | `--sync-from` |
| install | phantom slash refs | an installed lk SKILL.md (or legacy copy) names a backticked slash command that is not an installed skill, a `~/.claude/commands` command, or a Claude Code built-in (bare paths like `/tmp` are ignored) | edit the reference |
| install | python + pyyaml | pyyaml not importable, or the interpreter the okf shim picks (first of python3, python, py that runs) cannot import it | `pip install pyyaml` |
| install | `cleanupPeriodDays` | unset or under 365 in `~/.claude/settings.json`; older transcripts get pruned, and backfill loses its sources | set it to 3650 |
| project | `ai/okf.conf` | missing, or `archive` is not local, shared or off | edit the conf |
| project | `ai/scripts/okf` | the engine the shim resolves (honouring `OKF_SKILL_DIR` / `OKF_NORMALIZE`) does not exist (FAIL), or resolves through a legacy copy (WARN) | `--fix-shims` |
| project | bundle vocabulary | legacy keys (`timestamp`, `updated`, `source`, `verified_on`) or statuses (`unverified`, `verified`, `stale`, `open`, `closed`), with counts (WARN); a v0.2 bundle with a status outside `draft`, `stable`, `deprecated` (FAIL) | `ai/scripts/okf --apply` |
| project | root index | `ai/memory/index.md` lacks `okf_version: "0.2"` | `ai/scripts/okf --reindex` |
| project | promotion queue | more than 25 notes at `draft` (or legacy `unverified`) | `/lk-audit-knowledge` |

## Fix verbs (dry run unless `--yes`)

A fix verb runs instead of the checks. It prints exactly what it would do; add `--yes` to do it.
Run the plain check again afterwards to confirm.

| Verb | Does | Safety |
|---|---|---|
| `--sync-from CLONE` | copies `skills/lk-*` from the clone over the install, listing each file it adds or updates (by hash) | never deletes a file that exists only in the install unless `--prune` is also given; skips `__pycache__` and `.pytest_cache` |
| `--remove-legacy` | deletes the unprefixed pre-rename copies | only a copy whose `lk-` counterpart is installed, and only a dir that is ours (its SKILL.md `name:` matches; `reference` must hold `transcript-safety.md`) |
| `--fix-shims` | in the project's `ai/scripts/okf`, renames a legacy default skill dir to its `lk-` name and prints the diff | changes only the `${OKF_SKILL_DIR:-...}` default; line endings kept |

The upgrade, in order (repoint the shims before removing the legacy copies they may still run):

```bash
D=~/.claude/skills/lk-doctor/lk_doctor.py   # first install from a clone? use <clone>/skills/lk-doctor/lk_doctor.py
python $D --sync-from <clone>               # read the list
python $D --sync-from <clone> --yes
python $D --fix-shims --yes                 # from each project root that has ai/
python $D --remove-legacy --yes
python $D --repo <clone>                    # confirm: no FAIL
```

## When to run it

- Right after any `cp -r` install or upgrade of the skills.
- At the start of a session in a new project, or one you have not opened since the last upgrade,
  and right after cloning a project that has an `ai/` folder.
- When a shim fails with `engine not found`, a slash command does nothing, or anything in the lk
  system feels off.

## What lk-doctor does NOT do

- It does not judge note quality (stale facts, weak sources, missing links). That is
  `/lk-audit-knowledge`.
- It does not migrate a bundle to OKF v0.2. That is `ai/scripts/okf --apply`, then `--reindex`.
- It does not edit `~/.claude/settings.json`. It tells you which value is wrong.
- It checks only the lk skills and their project wiring. Any other skill in the skills dir, and any
  other tool's scripts, `ai/okf.conf` keys or hooks in a project, are left alone.
- It writes nothing without `--yes`.
