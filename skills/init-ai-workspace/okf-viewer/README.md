# OKF viewer (vendored)

Renders an [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
bundle (a directory of markdown files with YAML frontmatter — e.g. our `ai/memory/`) to a single
self-contained HTML file with a force-directed graph, type filter, full-text search, and per-note
detail panels with rendered markdown.

## Use

```bash
python ai/scripts/okf-viewer/render.py ai/memory ai/scripts/okf-viewer/okf-memory-graph.html "my ai/memory"
```

Open the resulting `okf-memory-graph.html` in a browser.

## Requirements & caveats

- **Deps:** Python 3.10+ and `pyyaml` only. No BigQuery / google-adk / pydantic (the heavy deps in
  upstream's `enrichment-agent` package are for the *enrichment* path, not rendering).
- **Needs internet to render.** The HTML is one file, but it loads `cytoscape` and `marked` from a
  jsDelivr CDN via `<script src>`. To make it truly offline, inline those two libs into
  `enrichment_agent/viewer/templates/viz.html` (replace the two `<script src=...>` tags with the
  library contents in `<script>` blocks).
- **Nesting-aware.** Concepts may live in topic subdirs (`acme/`, `crm/`); the viewer recurses,
  builds hierarchical concept-ids (`acme/schema_mysql-tables`), and skips every `index.md`.
- **Graph value is gated on inline cross-links.** OKF builds edges from markdown links *inside*
  concept bodies, not from the generated `index.md` files (reserved, skipped). Our notes don't yet
  link each other, so the graph renders as disconnected nodes — search / filter / detail still work.
  Add `[other note](../crm/gotcha_x.md)` links in note bodies to populate the graph.

## What's vendored

Copied from `okf/src/enrichment_agent/` (rendering path only):
`viewer/generator.py`, `viewer/__init__.py`, `bundle/document.py`, `viewer/templates/viz.html`,
`viewer/static/{viz.css,viz.js}`. The package `__init__.py` files are blanked to avoid pulling in
the enrichment/BigQuery modules.

**Local patch:** `viewer/generator.py` skips `INDEX.md` case-insensitively (upstream only skips
lowercase `index.md`; we use `INDEX.md`), so our TOC isn't rendered as a junk "Unknown" node.
