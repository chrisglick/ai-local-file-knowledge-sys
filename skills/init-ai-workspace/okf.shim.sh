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
#   ai/scripts/okf --distill ...  # distill this session's transcript into a citable md record
#   ai/scripts/okf --version
# Pass an explicit bundle dir as the first arg to override the default (ai/memory).
set -euo pipefail
SKILL="${OKF_SKILL_DIR:-$HOME/.claude/skills/init-ai-workspace}"
ENGINE="${OKF_NORMALIZE:-$SKILL/okf_normalize.py}"
VIEWER="$SKILL/okf-viewer/render.py"
DISTILL="$SKILL/distill_transcript.py"
# Pick an interpreter that actually RUNS. `command -v python3` is not enough: on default Windows
# it resolves to the Microsoft Store alias stub, which prints "Python was not found" and exits 49.
# Only a real interpreter echoes 42. (macOS/Linux often ship python3 but no python; `py` is the
# Windows launcher.)
PY=""
for _c in python3 python py; do
  if [ "$(command -v "$_c" >/dev/null 2>&1 && "$_c" -c 'print(42)' 2>/dev/null)" = "42" ]; then
    PY="$_c"; break
  fi
done
BUNDLE="ai/memory"
if [ "${1:-}" != "" ] && [ -d "${1:-}" ]; then BUNDLE="$1"; shift; fi
export PYTHONIOENCODING=utf-8
if [ -z "$PY" ]; then
  echo "okf: no working python found (tried python3, python, py)." >&2
  echo "  On Windows, 'python3' may be the Microsoft Store alias stub rather than an interpreter --" >&2
  echo "  install Python, or turn the alias off in Settings > Apps > Advanced > App execution aliases." >&2
  exit 127
fi
if [ ! -f "$ENGINE" ]; then
  echo "okf: engine not found at $ENGINE -- install the init-ai-workspace skill, or set OKF_SKILL_DIR." >&2
  exit 127
fi
if [ "${1:-}" = "--render" ]; then
  shift
  exec "$PY" "$VIEWER" "$BUNDLE" "${1:-ai/okf-memory-graph.html}" "OKF memory"
fi
if [ "${1:-}" = "--distill" ]; then
  shift
  exec "$PY" "$DISTILL" "$@"
fi
exec "$PY" "$ENGINE" "$BUNDLE" "$@"
