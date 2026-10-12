# okf_normalize.py — the OKF bundle engine

Maintains an `ai/memory/` knowledge bundle to the literal [OKF](https://github.com/GoogleCloudPlatform/open-knowledge-format)
**v0.2** standard (markdown + YAML frontmatter), speaking the spec's own vocabulary for provenance,
trust and lifecycle (`generated` / `sources` / `status` / `verified` / `stale_after`) and preserving
our anti-rot extensions (`created`, typed `relations`, the body's `**Verify:**` line — see
`ai/CAPTURE.md`). One file, **pyyaml-only**, ASCII-safe stdout (Windows-console clean).
Tests: `pytest test_okf_normalize.py`.

## Verbs

| Command | What it does |
|---|---|
| `okf_normalize.py BUNDLE` | dry-run report — frontmatter drift (incl. legacy keys to migrate), provenance/link/trust warnings, renames, foldering hint. Read-only. |
| `okf_normalize.py BUNDLE --check` | strict: same report, **exit 1 on ANY drift/error/warning/broken-link/rename**. For hooks/CI. |
| `okf_normalize.py BUNDLE --gate` | like `--check` but fails only on **mechanical** drift (what a Stop hook can act on). |
| `okf_normalize.py BUNDLE --apply` | rewrite frontmatter in place, **migrating the legacy vocabulary to v0.2** (table below). Auto-backs up to `../.okf-backups/<bundle>-<date>/` when not in a git repo. |
| `okf_normalize.py BUNDLE --reindex` | regenerate root + per-topic `index.md` from frontmatter; stamps `okf_version: "0.2"` on the root index. Preserves prose above the `<!-- okf-index:auto -->` marker; **refuses** to clobber a non-empty index lacking the marker unless `--force`. |
| `okf_normalize.py BUNDLE --move SRC DST` | move a note and **rewrite every inbound markdown link** (resolution-based, across `--root`, default = git root / cwd). Then run `--reindex`. |
| `okf_normalize.py BUNDLE --touch PATH...` | bump a note's `generated.at` (last meaningful change) to today; ensure `created` exists. |
| `okf_normalize.py BUNDLE --review` | read-only: list `status: draft` concepts (title + sources) — the **promotion queue** a human reviews. Used by `/lk-backfill-memory` and `/lk-audit-knowledge`. |
| `okf_normalize.py BUNDLE --promote PATH... [--actor human:<id>]` | **the only thing that writes trust**: sets `status: stable`, appends a `verified: [{by, at}]` entry, sets `stale_after` (+90d). Refuses a non-`human:` actor — promotion is a human act. |
| `okf_normalize.py BUNDLE --suggest-links` | read-only: surface note **pairs** that share salient terms but have no link/relation yet (drops corpus-generic terms). A HINT — the agent adds typed `relations` only where a real relationship exists. |
| `okf_normalize.py --version` | print tool + OKF-standard + lk version. |

Repo shim: `ai/scripts/okf --check` (bundle defaults to `ai/memory`).

### Actor resolution

`generated.by` on migrated notes and `verified.by` on promotion come from, in order: `--actor`,
the `actor = human:<id>` key in `ai/okf.conf`, `human:<git config user.name>` (slugified),
`human:unknown`. Tools that write notes name themselves (`lk-backfill-memory/1.0`,
`claude-code/<model-id>`); only `--promote` ever writes a `human:` actor into `verified`.

## What it checks / normalizes

- **Frontmatter** (canonical order): `type` (required, non-empty), `title`, `description`,
  `generated: {by, at}` (producer + last meaningful change), `created` (set-once), `sources:
  [{resource}]` (mandatory for us), `status` (`draft | stable | deprecated`, absent = stable),
  `verified: [{by, at}]`, `stale_after`, `relations`. `tags` are **optional** (never auto-stubbed).
- **Legacy migration** (each is reported as a change; `--apply` writes it):

  | legacy | v0.2 |
  |---|---|
  | `timestamp` / `updated` | `generated.at` (+ `generated.by` from the actor rules) |
  | `source: "a; b"` | `sources: [{resource: a}, {resource: b}]` |
  | `status: unverified` / `verified` / `stale` | `draft` / `stable` / `deprecated` |
  | `status: open` / `closed` (open-questions) | `draft` / `deprecated` |
  | `verified_on: DATE` | `verified: [{by: <actor>, at: DATE}]` + `stale_after: DATE + 90d` |

- **Provenance (our differentiator):** flags missing `sources` / `**Verify:**`, a source path that
  no longer resolves, a prose session citation, and a `deprecated` note with no resolving successor
  relation (a deprecated note that `supersedes`/`relates` to an existing note is a normal lifecycle
  end, e.g. an open-question superseded by a decision note, and does not warn).
- **Trust / lifecycle:** a `stable` note with no `verified` entry, a `verified.by` that isn't a
  spec actor shape (`human:` / `process:` / `<producer>/<version>`), a passed `stale_after`, or
  (when `stale_after` is absent) a verification older than 90 days.
- **Link integrity:** every `](*.md)` link resolves; broken links reported (the viewer hides them).
- **Renames** (`INDEX.md→index.md`, off-convention filenames) are **reported**, not auto-done — use
  `--move` (which fixes links) or `/lk-init-ai-workspace` Phase 4.
- **Foldering hint:** when flat and ≥20 concepts, prints a slug-token tally as a *rough* starting
  point — the agent refines it into real topic folders (placement only; never combines files).

## Versioning

`TOOL_VERSION` / `OKF_STANDARD_VERSION` / `LK_VERSION` are stamped at the top. Bump `TOOL_VERSION`
on behavior changes so projects can tell when their workflow is behind; `/lk-doctor` compares the
installed copy against the repo clone. `--version` prints all three.
