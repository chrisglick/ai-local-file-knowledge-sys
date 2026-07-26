#!/bin/sh
# govern-work Stop hook -- calls `gov --gate` when a Claude Code session ends.
#
# This is the Stop hook the underlying knowledge system's own docs say it does not ship
# ("No Stop hook ships here" -- KNOWLEDGE-SYSTEM.md Limitations). Its job is to move the
# ledger-write duty from mid-work (where it competes with the agent's loaded context and
# reliably gets skipped) to a mechanically-checked boundary (session close), per the brief's
# core diagnosis.
#
# MUST NEVER WEDGE A SESSION. Any missing dependency -- no working python, no govern-work
# skill installed, no `ai/scripts/gov` shim in this repo, not a git repo at all -- degrades to
# a one-line note on stderr and exit 0. Only a REAL gate result (the shim actually ran and
# `govern.py --gate` returned something) is propagated as this hook's own exit code. A
# refusal from an actual gate failure is meant to surface; an absent dependency is not a gate
# failure and must not be treated as one.
#
# INSTALLATION: wire this script as the Claude Code Stop hook (see the harness's hook
# configuration, e.g. via the `update-config` skill / settings.json `hooks.Stop`). It expects
# to run with the project repo as (or under) its working directory.

top=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "govern stop-gate: not inside a git repository, skipping." >&2
  exit 0
}

shim="$top/ai/scripts/gov"
if [ ! -f "$shim" ]; then
  echo "govern stop-gate: no ai/scripts/gov shim in this repo (govern-work not initialized here), skipping." >&2
  exit 0
fi

if [ -x "$shim" ]; then
  "$shim" --gate
  rc=$?
else
  # Exec bit didn't survive a checkout (common on some Windows setups) -- fall back to
  # explicitly interpreting it rather than failing the whole hook over a permission bit.
  sh "$shim" --gate
  rc=$?
fi

# The shim's own interpreter probe (identical in shape to init-ai-workspace/okf.shim.sh: try
# python3/python/py, confirm each actually runs by checking it prints 42 -- `command -v` alone
# is not enough, since on default Windows `python3` may resolve to the Microsoft Store alias
# stub, which prints "Python was not found" and exits 49) exits 127 when no working
# interpreter was found, or when the govern-work engine isn't installed at GOV_SKILL_DIR/
# GOV_ENGINE. Exit 127 is that shim's own "command not found"-style signal for infrastructure
# absence, not a real gate result -- degrade gracefully rather than propagate it.
if [ "$rc" -eq 127 ]; then
  echo "govern stop-gate: gov shim could not run (no working python, or the govern-work engine isn't installed), skipping." >&2
  exit 0
fi

exit "$rc"
