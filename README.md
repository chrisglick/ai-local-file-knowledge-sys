# ai-local-file-knowledge-sys

Three Claude Code skills that give a repo a **local, in-repo, git-tracked knowledge base** — so a
fact gets distilled once and retrieved cheaply, instead of re-derived from code and chat every
session.

Knowledge lives in `ai/memory/` as an [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
(OKF) bundle: plain markdown + YAML frontmatter, one concept per file, every note carrying its
`source` and a `**Verify:**` line. No database, no service, no vendor. It clones with the repo and
reads fine in any text editor.

**Design doc: [KNOWLEDGE-SYSTEM.md](KNOWLEDGE-SYSTEM.md)** — structure, format, disciplines,
strengths, and limitations. Read that for the *why*; this file is the *how to run it*.
**Version history and upgrade warnings: [CHANGELOG.md](CHANGELOG.md).**

## The three skills

| Skill | Does | When |
|---|---|---|
| [`init-ai-workspace`](skills/init-ai-workspace/) | Scaffold + normalize the `ai/` structure. Idempotent, non-destructive. | Onboard a project / fix format drift |
| [`backfill-memory`](skills/backfill-memory/) | Bulk-seed memory from static assets (notes, DB schema, config, code). Every claim cited or dropped. Output lands `status: unverified`. | Once, on un-distilled history |
| [`end-session`](skills/end-session/) | Capture the session; beat the 3 deaths of context (chat ends / one machine / fresh clone). | Every session close |

`init` + `end-session` are operator-incremental. `backfill` is one-time mining.

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
python ~/.claude/skills/init-ai-workspace/okf_normalize.py --version
# okf_normalize tool 0.8; OKF standard 0.1
```

Optionally run the test suite (needs `pip install pytest`):

```bash
cd ~/.claude/skills/init-ai-workspace && python -m pytest -q   # 51 passed
```

**Upgrading from 0.7?** `--check` now warns on any `source:` that can't be opened — notes citing a
session in prose will start failing. That's intended (those citations were never checkable), but
it isn't silent: run `ai/scripts/okf --check` after updating. See [CHANGELOG.md](CHANGELOG.md).

## Quickstart

In any project, ask Claude Code to run `/init-ai-workspace`. It scaffolds:

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

Then `/end-session` at each session close. If the project has years of undistilled history, run
`/backfill-memory` once to seed it.

**Run `/init-ai-workspace` sooner rather than later.** Claude Code deletes session files older than
`cleanupPeriodDays` ([default 30](https://code.claude.com/docs/en/settings)) at startup. Anything
older than that window is already gone — archiving protects sessions from the day you adopt it, and
`/backfill-memory` cannot mine transcripts that no longer exist.

## The engine

`okf_normalize.py` (one file, `pyyaml`-only) lives **once** in the skill dir. Projects carry only a
10-line `ai/scripts/okf` shim, so there's one engine to upgrade and nothing vendored per repo.

| Verb | Purpose |
|---|---|
| `--check` / `--gate` | strict conformance / mechanical-drift-only |
| `--apply` | rewrite frontmatter to canonical form |
| `--reindex` | regenerate `index.md` from frontmatter |
| `--move SRC DST` | move a note + rewrite inbound links |
| `--review` | print the `status: unverified` promotion queue |
| `--suggest-links` | surface note pairs not yet linked |
| `--render` | regenerate the graph HTML |
| `--distill` | archive this session's transcript as a citable record |

Full reference: [`okf_normalize.README.md`](skills/init-ai-workspace/okf_normalize.README.md).

### Citing a conversation

`source: src/auth/login.ts:42` works when a fact lives in code. A **decision**'s *why* was argued in
a chat — cite that as `session 2026-06-19` and nobody can open it, so the note can never be
re-checked. Worse, Claude Code deletes session files older than `cleanupPeriodDays`
(**[default 30](https://code.claude.com/docs/en/settings)**), so even a chat link dangles right when
you need it.

`/end-session` archives each session into the repo, and `--check` warns on any `source:` that can't
be opened:

```
decision_prose-source.md
  ? `source` names a session/plan in prose, not a resolvable path -- cite the archived transcript
decision_pruned.md
  ? `source` path not found: ai/session/raw/deadbeef-....md
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

The shim resolves the engine at `~/.claude/skills/init-ai-workspace/`. Override with
`OKF_SKILL_DIR` if you install elsewhere. A clone without the skill installed gets a shim that
exits 127 — the data is still plain markdown and reads fine; only the tooling is absent.

## Scope and honest limits

This is a scaffold for diligence, not a substitute for it. Trust rests on discipline plus human
review, not on mechanism. The failure mode is a growing `unverified` queue and an edgeless graph —
not a crash. [KNOWLEDGE-SYSTEM.md](KNOWLEDGE-SYSTEM.md#limitations) lists the limitations in full;
the ones to know before adopting:

- **Capture is not automatic.** It's operator-dependent — you have to run `/end-session`.
- **Nothing forces review.** The promotion queue is unbounded; unvouched facts accumulate.
- **Archiving starts the day you adopt it.** Sessions already pruned by `cleanupPeriodDays` are
  gone; raising the setting protects only what's left. Run `/init-ai-workspace` early.
- **Secret scanning is issuer-shaped only.** Committing a distilled transcript stays a human call.
- **Only Claude Code writes an archivable transcript.** On claude.ai / Cowork the source is a chat
  no `source:` can durably resolve.
- **The anti-hallucination gate is prompt-enforced, not guaranteed.** The codebase adapter in
  `backfill-memory` is the highest-risk surface.
- **No Stop hook ships here.** `KNOWLEDGE-SYSTEM.md` and the shim's `--gate` verb describe a
  drift-check Stop hook living in `~/.claude/hooks/`. That hook is not part of this repo — wire
  `ai/scripts/okf --gate` into your own hook config if you want it enforced automatically.
- **Cross-platform friction.** Windows backslash paths and case-insensitive filesystem renames
  both need care (the skills call this out where it bites).

## Licensing

- Original work — the `okf_normalize.py` engine, the three skills, templates, and shim — is **MIT**
  ([LICENSE](LICENSE)).
- `skills/init-ai-workspace/okf-viewer/` is **vendored from Google Cloud Platform's
  [`knowledge-catalog`](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)**
  (`okf/src/enrichment_agent/`) and remains **Apache-2.0**. One local patch (case-insensitive
  `index.md` skip) was applied. See
  [`okf-viewer/UPSTREAM-LICENSE.md`](skills/init-ai-workspace/okf-viewer/UPSTREAM-LICENSE.md).

## Prior art

Open Knowledge Format (Google Cloud Platform `knowledge-catalog`) is the standard the bundle
targets. Note-shape borrows from `cq` knowledge commons (summary→detail→action, confirm-or-decay),
`beads` (typed relations), and the Zep bi-temporal model (`valid_as_of`).
