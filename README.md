# ai-local-file-knowledge-sys

Five Claude Code skills — all prefixed `lk-` (*local knowledge*) so they group together in
`~/.claude/skills` — that give a repo a **local, in-repo, git-tracked knowledge base** — so a
fact gets distilled once and retrieved cheaply, instead of re-derived from code and chat every
session — plus an enforcement layer that gates on the ledger instead of asking an agent to
remember it.

Knowledge lives in `ai/memory/` as an [Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format)
(OKF) bundle: plain markdown + YAML frontmatter, one concept per file, every note carrying its
`source` and a `**Verify:**` line. No database, no service, no vendor. It clones with the repo and
reads fine in any text editor.

**Design doc: [KNOWLEDGE-SYSTEM.md](KNOWLEDGE-SYSTEM.md)** — structure, format, disciplines,
strengths, and limitations. Read that for the *why*; this file is the *how to run it*.
**Version history and upgrade warnings: [CHANGELOG.md](CHANGELOG.md).**

## The five skills

| Skill | Does | When |
|---|---|---|
| [`lk-init-ai-workspace`](skills/lk-init-ai-workspace/) | Scaffold + normalize the `ai/` structure. Migrates a bundle to OKF v0.2. Idempotent, non-destructive. | Onboard a project / fix format drift |
| [`lk-backfill-memory`](skills/lk-backfill-memory/) | Bulk-seed memory from static assets (notes, DB schema, config, code). Every claim cited or dropped. Output lands `status: draft`. | Once, on un-distilled history |
| [`lk-end-session`](skills/lk-end-session/) | Capture the session; beat the 3 deaths of context (chat ends / one machine / fresh clone). | Every session close |
| [`lk-audit-knowledge`](skills/lk-audit-knowledge/) | Quality triage of a bundle: machine-filed bursts, near-duplicates, low-information, stale and orphan notes → an editable plan a human approves before anything is deleted. | After a build campaign filed many notes; before promoting a backfill |
| [`lk-doctor`](skills/lk-doctor/) | Health check of the install and a project's wiring: skill versions, drift against the repo clone, phantom `/skill` references, legacy vocabulary, shim paths, hooks. Safe fixes behind `--yes`. | After installing or upgrading; when anything feels off |

`init` + `end-session` are operator-incremental. `backfill` is one-time mining. `audit-knowledge`
and `doctor` keep the other three honest — the first judges what the system *holds*, the second
checks that the system *itself* is intact.

## Install

Copy the skills into your Claude Code skills directory:

```bash
git clone https://github.com/chrisglick/ai-local-file-knowledge-sys.git
mkdir -p ~/.claude/skills
cp -r ai-local-file-knowledge-sys/skills/* ~/.claude/skills/
pip install pyyaml
```

`mkdir -p` matters: `cp` fails with *"target is not a directory"* if you've never created a skill
before. On Windows PowerShell, swap the copy for
`Copy-Item -Recurse ai-local-file-knowledge-sys\skills\* $HOME\.claude\skills\`.

`pyyaml` is the only runtime dependency — the transcript distiller is stdlib-only. Verify:

```bash
python ~/.claude/skills/lk-init-ai-workspace/okf_normalize.py --version
# okf_normalize tool 0.9; OKF standard 0.2; lk 1.0.0
```

Then let the system check itself — every lk skill present, no leftover unprefixed copies, the
engine on OKF 0.2, no `/skill` reference in any SKILL.md that names a skill you don't have:

```bash
python ~/.claude/skills/lk-doctor/lk_doctor.py
```

Inside a project, add `--project .` and it also checks the shims, `ai/okf.conf`, and whether the
bundle still uses pre-v0.2 vocabulary.

Optionally run the test suite (needs `pip install pytest`):

```bash
cd ~/.claude/skills && python -m pytest -q lk-*   # every lk skill ships its tests
```

Contributors run `python -m pytest -q` from the clone root instead: that adds
`tests/test_skill_docs.py`, the docs-versus-code contract (every `/skill` a SKILL.md names
exists, every `--flag` it tells the agent to run exists in the script, every template a phase
says to copy ships, every relative link resolves). Three of the five skills are prose and
can't be unit-tested; this is the test for the way prose actually rots.

**Upgrading from a pre-1.0 install?** Three things changed at once: the skills are now named
`lk-*` (delete the old unprefixed copies, or let `lk-doctor --remove-legacy` do it), project shims
that still point at the old names need `lk-doctor --fix-shims`, and every bundle needs
`ai/scripts/okf --apply` to migrate to the OKF v0.2 vocabulary (`--check` treats the old keys as
drift until you do). Run `/lk-doctor` first; it names each of these. See [CHANGELOG.md](CHANGELOG.md).

## Read this before you use it on a public repo

This system writes what you and Claude did into your repo. That's the point — but two of those
things can publish something you didn't mean to publish. You don't need to be a security person to
stay safe here; you need to know these four facts.

**1. `git push` is permanent.** Deleting a file later does not undo it. Git keeps every old version
in its history, and anyone who cloned or forked already has a copy. If a password or API key ever
lands in a public repo, deleting it does nothing — **you have to change the key itself** (rotate
it). Assume anything pushed to a public repo is public forever.

**2. Conversations get saved, and you choose how far they travel.** `/lk-end-session` can save the
session into `ai/session/raw/` so your notes can point at *why* you decided something. A
conversation holds whatever was said in it: client names, unreleased plans, personal details, a key
someone pasted in. `ai/okf.conf` controls this, and **the default is the safe one**:

| `archive =` | What happens | Use it when |
|---|---|---|
| **`local`** *(default)* | Saved on your computer, **gitignored**. Never pushed. | Almost always. Always, if unsure. |
| `shared` | Saved **and committed** — ships to anyone who can read the repo. | Private repo, and you accept that |
| `off` | Not saved at all. | The work is confidential |

You don't have to trust yourself to remember: in `local` mode the tool **refuses to write** the
transcript anywhere git isn't ignoring. The raw `.jsonl` is refused in *every* mode — it contains
the output of every command Claude ran, which can include your environment variables and file
contents.

**3. The secret scanner is not a safety net.** It finds keys shaped like keys (`ghp_…`, `sk-ant-…`,
`AKIA…`) and blanks them out. It **cannot** find passwords, database connection strings, personal
data, or internal hostnames — those look like ordinary writing. When it says `0 hits` it means
*"nothing obvious"*, never *"safe to publish"*.

**4. On a public repo, keep the knowledge base out of git.** `/lk-end-session` writes runbooks
describing where your credentials live and how to refresh them. That's useful to you and a map for
a stranger. For a public repo, `/lk-init-ai-workspace` will detect it (`gh repo view --json
visibility`) and recommend gitignoring `ai/session/` — or all of `ai/`. You lose "the notes survive
a fresh clone", which is a real cost and the right trade: an unreviewed publish is worse than a
lost note. Commit `ai/` on a public repo **only if you will read every file before every push.**

> **If you think you already leaked a key:** rotate it now — revoke the old one and issue a new one.
> Then worry about the file. Rotating is the only step that actually works.

## Quickstart

In any project, ask Claude Code to run `/lk-init-ai-workspace`. It scaffolds:

```
project-root/
├── README.md   # human front door; <!-- knowledge-system --> block links into ai/
├── CLAUDE.md   # agent router; opens ai/README.md FIRST at session start
├── RESUME.md   # active thread: state + single next action
├── STATUS.md   # project + plan status
└── ai/
    ├── README.md   # index of indexes
    ├── CAPTURE.md  # capture protocol + provenance rules
    ├── memory/     # the OKF bundle (timeless wiki)
    ├── plans/      # feature specs (frozen when built)
    ├── session/    # dated journal (append-only)
    │   └── raw/    # archived transcripts: <id>.md committed, <id>.jsonl gitignored
    └── scripts/okf # 10-line shim → the global engine
```

Then `/lk-end-session` at each session close. If the project has years of undistilled history, run
`/lk-backfill-memory` once to seed it.

**Run `/lk-init-ai-workspace` sooner rather than later.** Claude Code deletes session files older than
`cleanupPeriodDays` ([default 30](https://code.claude.com/docs/en/settings)) at startup. Anything
older than that window is already gone — archiving protects sessions from the day you adopt it, and
`/lk-backfill-memory` cannot mine transcripts that no longer exist.

## The engine

`okf_normalize.py` (one file, `pyyaml`-only) lives **once** in the skill dir. Projects carry only a
10-line `ai/scripts/okf` shim, so there's one engine to upgrade and nothing vendored per repo.

| Verb | Purpose |
|---|---|
| `--check` / `--gate` | strict conformance / mechanical-drift-only |
| `--apply` | rewrite frontmatter to canonical form |
| `--reindex` | regenerate `index.md` from frontmatter |
| `--move SRC DST` | move a note + rewrite inbound links |
| `--review` / `--promote` | print the `status: draft` promotion queue / human-promote a note (`stable` + `verified` entry + `stale_after`) |
| `--suggest-links` | surface note pairs not yet linked |
| `--render` | regenerate the graph HTML |
| `--distill` | archive this session's transcript as a citable record |

Full reference: [`okf_normalize.README.md`](skills/lk-init-ai-workspace/okf_normalize.README.md).

### Citing a conversation

A `sources` entry of `src/auth/login.ts:42` works when a fact lives in code. A **decision**'s *why* was argued in
a chat — cite that as `session 2026-06-19` and nobody can open it, so the note can never be
re-checked. Worse, Claude Code deletes session files older than `cleanupPeriodDays`
(**[default 30](https://code.claude.com/docs/en/settings)**), so even a chat link dangles right when
you need it.

`/lk-end-session` archives each session into the repo, and `--check` warns on any `sources` entry that can't
be opened:

```
decision_prose-source.md
  ? `sources` names a session/plan in prose, not a resolvable path -- cite the archived transcript
decision_pruned.md
  ? `sources` path not found: ai/session/raw/deadbeef-....md
```

Two files land per session, and **the split is a safety boundary, not tidiness**:

| File | Contents | Git |
|---|---|---|
| `<id>.md` | human + assistant prose (~4% of raw) | **committed** — the citation target |
| `<id>.jsonl` | untouched transcript | **gitignored** — holds tool output |

Tool results (`env` dumps, file reads, stdout) are ~31% of a raw transcript and carry effectively
all of its secret exposure; the conversation is ~3%. The distiller drops tool results, tool calls,
and reasoning **by block type** — a structural exclusion, deterministic in a way secret-scanning
isn't. A known-shape scan (`ghp_`, `sk-ant-`, `AKIA`, JWTs, PEM blocks…) then redacts what it can,
but **`0 hits` is not a clearance** — passwords, PII, and internal hostnames have no detectable
shape. Read the file before committing it.

The shim resolves the engine at `~/.claude/skills/lk-init-ai-workspace/`. Override with
`OKF_SKILL_DIR` if you install elsewhere. A clone without the skill installed gets a shim that
exits 127 — the data is still plain markdown and reads fine; only the tooling is absent.

## `lk-audit-knowledge` and `lk-doctor` — the two that keep the rest honest

Both were born from the same afternoon on a real project. A build-orchestration tool filed one
note per *paragraph* of six completion reports, and the bundle woke up with 118 well-formed,
near-empty `pattern` notes. `okf --check` passed: format
checks can't tell garbage from knowledge. The skill docs pointed at an `/audit-knowledge` that had
never been written, the installed engine had drifted 36 lines from the repo clone, and the
normalizer still claimed OKF 0.1 while upstream had moved to 0.2.

[`lk-audit-knowledge`](skills/lk-audit-knowledge/) is the quality pass: a heuristic engine finds
machine bursts, near-duplicates, low-information bodies, passed `stale_after` dates and orphans,
writes an **editable plan**, the agent judges each cluster (never trusting the heuristic blindly),
and a **human approves** before `--apply` deletes anything. Deletions are `git rm`, so they're
recoverable; file contents are never merged by a script.

[`lk-doctor`](skills/lk-doctor/) is the system check: are all six skills installed, do the
installed copies match the repo clone, does every `` `/skill` `` a SKILL.md mentions actually
exist, is the engine on the current OKF standard, do a project's shims resolve, does its bundle
still use the legacy vocabulary. PASS/WARN/FAIL per check, every fix verb dry-run by default.

## Scope and honest limits

This is a scaffold for diligence, not a substitute for it. Trust rests on discipline plus human
review, not on mechanism. The failure mode is a growing `draft` queue and an edgeless graph —
not a crash. [KNOWLEDGE-SYSTEM.md](KNOWLEDGE-SYSTEM.md#limitations) lists the limitations in full;
the ones to know before adopting:

- **Capture is not automatic.** It's operator-dependent — you have to run `/lk-end-session`.
- **Nothing forces review.** `lk-audit-knowledge` triages the queue, but promotion
  (`okf --promote`) is still a human act nobody can be made to perform, and the queue is unbounded.
- **Archiving starts the day you adopt it.** Sessions already pruned by `cleanupPeriodDays` are
  gone; raising the setting protects only what's left. Run `/lk-init-ai-workspace` early.
- **Secret scanning is issuer-shaped only.** Committing a distilled transcript stays a human call.
- **Only Claude Code writes an archivable transcript.** On claude.ai / Cowork the source is a chat
  no `sources` entry can durably resolve.
- **The anti-hallucination gate is prompt-enforced, not guaranteed.** The codebase adapter in
  `lk-backfill-memory` is the highest-risk surface.
- **No Stop hook ships.** `ai/scripts/okf --gate` is built for one (mechanical drift only, exit 1),
  but wiring it into Claude Code's hook config is a project choice you make yourself.
- **Cross-platform friction.** Windows backslash paths and case-insensitive filesystem renames
  both need care (the skills call this out where it bites).

## Licensing

- Original work — the `okf_normalize.py` engine, the five skills, templates, and shim — is **MIT**
  ([LICENSE](LICENSE)).
- `skills/lk-init-ai-workspace/okf-viewer/` is **vendored from Google Cloud Platform's
  [`open-knowledge-format`](https://github.com/GoogleCloudPlatform/open-knowledge-format)**
  (`okf/src/enrichment_agent/`) and remains **Apache-2.0**. One local patch (case-insensitive
  `index.md` skip) was applied. See
  [`okf-viewer/UPSTREAM-LICENSE.md`](skills/lk-init-ai-workspace/okf-viewer/UPSTREAM-LICENSE.md).

## Prior art

Open Knowledge Format (Google Cloud Platform `open-knowledge-format`, formerly `knowledge-catalog/okf`) is the standard the bundle
targets. Note-shape borrows from `cq` knowledge commons (summary→detail→action, confirm-or-decay),
`beads` (typed relations), and the Zep bi-temporal model (`valid_as_of`).
