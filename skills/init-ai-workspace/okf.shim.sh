#!/usr/bin/env bash
# Thin pointer to the GLOBAL OKF toolchain (engine + viewer live once in the
# init-ai-workspace skill; this repo carries only this 10-line shim + the ai/memory data).
#   ai/scripts/okf --check        # strict conformance (provenance + links + drift); exit 1 on any
#   ai/scripts/okf --gate         # mechanical drift only (what the Stop hook uses)
#   ai/scripts/okf --apply        # rewrite frontmatter (auto-backup when not in git)
#   ai/scripts/okf --reindex      # regenerate index.md files
#   ai/scripts/okf --move SRC DST # move a note + rewrite inbound links
#   ai/scripts/okf --touch PATH   # bump a note's timestamp to today
#   ai/scripts/okf --review       # list status: unverified notes (the backfill promotion queue)
#   ai/scripts/okf --suggest-links # surface note pairs sharing terms but not yet linked (a hint)
#   ai/scripts/okf --render [OUT] # render the graph HTML (default ai/okf-memory-graph.html)
#   ai/scripts/okf --version
# Pass an explicit bundle dir as the first arg to override the default (ai/memory).
set -euo pipefail
SKILL="${OKF_SKILL_DIR:-$HOME/.claude/skills/init-ai-workspace}"
ENGINE="${OKF_NORMALIZE:-$SKILL/okf_normalize.py}"
VIEWER="$SKILL/okf-viewer/render.py"
PY="$(command -v python3 || command -v python || true)"   # macOS/Linux often only have python3
BUNDLE="ai/memory"
if [ "${1:-}" != "" ] && [ -d "${1:-}" ]; then BUNDLE="$1"; shift; fi
export PYTHONIOENCODING=utf-8
if [ -z "$PY" ]; then echo "okf: no python/python3 on PATH." >&2; exit 127; fi
if [ ! -f "$ENGINE" ]; then
  echo "okf: engine not found at $ENGINE -- install the init-ai-workspace skill, or set OKF_SKILL_DIR." >&2
  exit 127
fi
if [ "${1:-}" = "--render" ]; then
  shift
  exec "$PY" "$VIEWER" "$BUNDLE" "${1:-ai/okf-memory-graph.html}" "OKF memory"
fi
exec "$PY" "$ENGINE" "$BUNDLE" "$@"
