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
git clone https://github.com/<you>/ai-local-file-knowledge-sys.git
cp -r ai-local-file-knowledge-sys/skills/* ~/.claude/skills/
```

The only dependency is Python with `pyyaml` (`pip install pyyaml`). Verify the engine:

```bash
python ~/.claude/skills/init-ai-workspace/okf_normalize.py --version   # okf_normalize tool 0.7; OKF standard 0.1
python -m pytest ~/.claude/skills/init-ai-workspace/test_okf_normalize.py -q   # 33 passed
```

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
    └── scripts/okf # 10-line shim → the global engine
```

Then `/end-session` at each session close. If the project has years of undistilled history, run
`/backfill-memory` once to seed it.

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

Full reference: [`okf_normalize.README.md`](skills/init-ai-workspace/okf_normalize.README.md).

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
