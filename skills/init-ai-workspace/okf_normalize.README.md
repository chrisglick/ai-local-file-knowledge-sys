# okf_normalize.py — the OKF bundle engine

Maintains an `ai/memory/` knowledge bundle to the literal [OKF](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
standard (markdown + YAML frontmatter), preserving our anti-rot extensions (`source` / `status` /
`**Verify:**`) plus agent-memory-research adoptions (`workaround` type, typed `relations`,
`verified_on` 90-day decay — see `ai/CAPTURE.md`). One file, **pyyaml-only**, ASCII-safe stdout
(Windows-console clean). Tests: `pytest test_okf_normalize.py`.

## Verbs

| Command | What it does |
|---|---|
| `okf_normalize.py BUNDLE` | dry-run report — frontmatter drift, provenance/link warnings, renames, foldering hint. Read-only. |
| `okf_normalize.py BUNDLE --check` | strict: same report, **exit 1 on ANY drift/error/warning/broken-link/rename**. For hooks/CI. |
| `okf_normalize.py BUNDLE --apply` | rewrite frontmatter in place. **Auto-backs up to `../.okf-backups/<bundle>-<date>/` when not in a git repo.** |
| `okf_normalize.py BUNDLE --reindex` | regenerate root + per-topic `index.md` from frontmatter. Preserves prose above the `<!-- okf-index:auto -->` marker; **refuses** to clobber a non-empty index lacking the marker unless `--force`. |
| `okf_normalize.py BUNDLE --move SRC DST` | move a note and **rewrite every inbound markdown link** (resolution-based, across `--root`, default = git root / cwd). Then run `--reindex`. |
| `okf_normalize.py BUNDLE --touch PATH...` | bump a note's `timestamp` (last meaningful change) to today; ensure `created` exists. |
| `okf_normalize.py BUNDLE --review` | read-only: list `status: unverified` concepts (title + source) — the backfill **promotion queue** a human reviews before flipping to `verified`. Used by the `/backfill-memory` skill. |
| `okf_normalize.py BUNDLE --suggest-links` | read-only: surface note **pairs** that share salient terms but have no link/relation yet (drops corpus-generic terms). A HINT for closing the edgeless graph — the agent adds typed `relations` only where a real relationship exists. |
| `okf_normalize.py --version` | print tool + OKF-standard version. |

Repo shim: `ai/scripts/okf --check` (bundle defaults to `ai/memory`).

## What it checks / normalizes

- **Frontmatter** (canonical order): `type` (required, non-empty), `title`, `description`,
  `timestamp` (ISO 8601, last meaningful change), `created` (set-once), then extensions
  `source` / `status`. `tags` are **optional** (no longer auto-stubbed — an always-empty field is cruft;
  populate them if you want the viewer's tag filter).
- **Provenance (our differentiator):** flags missing `source` / `**Verify:**`, a `source` path that
  no longer resolves, and `status: stale`.
- **Link integrity:** every `](*.md)` link resolves; broken links reported (the viewer hides them).
- **Renames** (`INDEX.md→index.md`, off-convention filenames) are **reported**, not auto-done — use
  `--move` (which fixes links) or `/init-ai-workspace` Phase 4.
- **Foldering hint:** when flat and ≥20 concepts, prints a slug-token tally as a *rough* starting
  point — the agent refines it into real topic folders (placement only; never combines files).

## Versioning

`TOOL_VERSION` / `OKF_STANDARD_VERSION` are stamped at the top. Bump `TOOL_VERSION` on behavior
changes so projects can tell when their workflow is behind. `--version` prints both.
