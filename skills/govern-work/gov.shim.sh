#!/usr/bin/env bash
# Thin pointer to the GLOBAL govern-work engine (lives once in the govern-work skill; this repo
# carries only this ~10-line shim). Copied verbatim in shape from init-ai-workspace/okf.shim.sh.
#   ai/scripts/gov --open "<question>"          file a type: open-question note
#   ai/scripts/gov --rule <note> --verbatim "…"  close an open-question into a decision note
#   ai/scripts/gov --lint-spec <file>            R5 sizing + R14 underspecification guards
#   ai/scripts/gov --ratchet                     exit 1 if a tracked count rose above baseline
#   ai/scripts/gov --baseline                    rewrite baseline, downward only
#   ai/scripts/gov --version
# Pass an explicit bundle dir as the first arg to override the default (ai/memory).
set -euo pipefail
SKILL="${GOV_SKILL_DIR:-$HOME/.claude/skills/govern-work}"
ENGINE="${GOV_ENGINE:-$SKILL/govern.py}"
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
export PYTHONIOENCODING=utf-8
if [ -z "$PY" ]; then
  echo "gov: no working python found (tried python3, python, py)." >&2
  echo "  On Windows, 'python3' may be the Microsoft Store alias stub rather than an interpreter --" >&2
  echo "  install Python, or turn the alias off in Settings > Apps > Advanced > App execution aliases." >&2
  exit 127
fi
if [ ! -f "$ENGINE" ]; then
  echo "gov: engine not found at $ENGINE -- install the govern-work skill, or set GOV_SKILL_DIR." >&2
  exit 127
fi
exec "$PY" "$ENGINE" "$@"
