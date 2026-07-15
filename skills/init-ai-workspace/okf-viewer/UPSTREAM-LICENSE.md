# Upstream license — okf-viewer/

The viewer code in this directory (`generator.py`, `bundle/document.py`, `viewer/templates/`,
`viewer/static/`) is **vendored from Google Cloud Platform's `knowledge-catalog` project**
(`okf/src/enrichment_agent/`), which is licensed under **Apache License 2.0**.

- Source: https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf
- License: Apache-2.0 (see the upstream `LICENSE`).

These files retain their original Apache-2.0 license. Only a one-line local patch (case-insensitive
`index.md` skip) was applied. The rest of this skill (the `okf_normalize.py` engine, templates, shim)
is original work under this repo's MIT license.
