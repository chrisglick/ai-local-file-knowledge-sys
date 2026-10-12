# Transcript safety — archiving conversations without leaking them

Shared reference for `/lk-end-session` (Phase 0) and `/lk-init-ai-workspace` (Phases 0, 2, 2.5).

## The retention deadline (`cleanupPeriodDays`)
Claude Code deletes session files older than `cleanupPeriodDays` at startup — **default 30 days**
when the key is absent from `~/.claude/settings.json`. That is the shelf life of every "why" a
project hasn't archived yet: a note that cites "the chat where we decided X" dangles on day 31 —
right when you finally need it. Raising it (`"cleanupPeriodDays": 3650`) is a one-line settings
edit but only protects sessions **from now on** — it cannot recover pruned ones, and
`/lk-backfill-memory` cannot mine what no longer exists. `/lk-end-session` Phase 0 archives each session
into the repo, which is what makes the setting stop mattering going forward.

## Archive modes (`ai/okf.conf`)
The archive contains what was actually said this session — client names, unreleased plans,
personal details, a credential someone pasted into chat. `ai/okf.conf` decides how far it travels,
and `distill_transcript.py` enforces that choice rather than trusting anyone to remember it: it
reads the config itself and **refuses to write an un-gitignored transcript in `local` mode**, so a
conversation can't be committed by accident. If it refuses, don't work around it by editing paths —
fix `.gitignore` (re-run `/lk-init-ai-workspace`) or change the mode deliberately.

| `archive =` | What happens | For |
|---|---|---|
| `local` *(default, incl. when no `ai/okf.conf` exists)* | Saved to `ai/<session-dir>/raw/`, **gitignored**. Never pushed. | Almost everyone |
| `shared` | Saved **and committed** — ships to anyone who can read the repo. | Private repos, informed choice |
| `off` | Not saved. Decisions then have no citable source. | Confidential work |

## The two-file split (a safety boundary)
- **`<id>.md` — human + assistant prose.** ~4% of the raw size. Tool results, tool calls, and
  reasoning are dropped **by block type** — a structural exclusion, not a secret-scan. Tool output
  is where keys actually land (an `env` dump, a config read, a command that prints a token);
  dropping the whole category is deterministic in a way pattern-matching never is. This is the
  committable artifact (under `shared` mode only).
- **`<id>.jsonl` — the untouched transcript. Never committed, in any mode** — the tool refuses if
  the path isn't gitignored. It survives `cleanupPeriodDays`, which is the point: it's the local
  fallback when the distilled record isn't enough evidence. It carries every tool result — env
  dumps, file contents, command stdout — however much it "looks like just a log."

The `.gitignore` rule `ai/<session-dir>/raw/*.jsonl` is therefore unconditional in every mode;
add `ai/<session-dir>/raw/*.md` when `archive = local`.

## Secret-scan caveats
The distiller's scan finds issuer-formatted tokens (`ghp_`, `sk-ant-`, `AKIA`, …) and redacts
them. It is blind to passwords, connection strings, PII, internal hostnames, and proprietary
data — those look like ordinary prose. **`0 hits` means "nothing obvious", never "safe to
publish".** Under `shared`, skim the file before it ships.

## Public repos: rotate, not delete
Anything committed to a public repo is public permanently. Deleting a file later does not help —
git keeps it in history, and forks, clones, and caches keep it after that. A leaked credential
must be **rotated**, not deleted. For a public repo (or one heading to a public host),
`archive = local` is the only sane mode — and consider gitignoring the knowledge files that
accumulate operational detail: runbooks describing *where* credentials live and how to refresh
them are useful to you and a map for a stranger.
