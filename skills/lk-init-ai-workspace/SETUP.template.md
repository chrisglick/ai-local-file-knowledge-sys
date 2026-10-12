# SETUP — fresh-clone checklist for {{PROJECT}}

> The steps a fresh clone needs that *fail silently* if skipped. Created by
> `/lk-init-ai-workspace`, which fills in what it can detect; keep it current when you add a
> step. Auth entries are **pointers** (where it lives, how to refresh, what expiry looks like),
> never values. This file is committed.

## 1. Tooling

- [ ] Python 3.11+ on PATH that actually runs (`python -c "print(42)"`). On Windows, `python3`
      may be the Microsoft Store stub — turn it off under *Settings › Apps › App execution aliases*.
- [ ] `pip install pyyaml` (the only dependency of the knowledge tooling).
- [ ] The lk skills installed: `python ~/.claude/skills/lk-doctor/lk_doctor.py --project .`
      reports 0 FAIL.

## 2. Git hooks and config that a clone does not carry

- [ ] (e.g. `git config core.hooksPath .githooks` — a `.githooks/` dir is inert until this is set)
- [ ] (e.g. `git config user.name` / `user.email` for this repo, if it differs from your global)

## 3. Environment and credentials (pointers only)

| What | Where it lives | How to get / refresh | Expiry symptom |
|---|---|---|---|
| (e.g. `.env`) | copy from `.env.example`, values from the team vault | ask the owner | app starts but every request 401s |
| (e.g. an API key) | gitignored `secrets/` dir | (refresh procedure) | (what breaks when it's stale) |

## 4. Knowledge system

- [ ] `ai/okf.conf` reviewed — `archive = local` unless you've read the "Read this before you use
      it on a public repo" section and chosen otherwise.
- [ ] `ai/scripts/okf --check` runs (exit 0 = conformant; exit 127 = engine not installed).
- [ ] `~/.claude/settings.json` has `"cleanupPeriodDays": 3650` (or ≥ 365) so session transcripts
      outlive the default 30-day purge — `/lk-backfill-memory` cannot mine what is gone.

## 5. First-run verification

- [ ] (the one command that proves the project works, e.g. the test suite or a smoke run)
- [ ] Read `RESUME.md` for the active thread, then `ai/README.md` for where everything lives.
