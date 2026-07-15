#!/usr/bin/env python3
"""Distill a Claude Code session transcript into a citable, committable markdown record.

Why this exists
---------------
A note that records a decision must be able to show where the decision came from. For code,
`source: src/auth/login.ts:42` does that. For a decision made in conversation there is no file
to point at -- so the note cites prose ("session 2026-06-19"), nobody can open it, and the claim
rots silently. Worse, Claude Code prunes its own transcripts after `cleanupPeriodDays` (default
30), so even a chat link dangles right when you finally need it.

This writes the conversation to a file in the repo, so `source:` names something that still
resolves in a year -- the way a commit hash does for code.

What it keeps, and why that is the safety model
-----------------------------------------------
Keeps ONLY human and assistant prose. Excludes tool results, tool calls, and reasoning blocks
*structurally* -- not by pattern-matching them. That distinction is the whole point: tool output
is where secrets actually land (an `env` dump, a config read, a command that prints a token), and
it is ~31% of a raw transcript's bytes while the conversation is ~3%. Dropping the category by
type is deterministic. Scanning it for secrets would not be -- see `scan_secrets`.

A known-shape secret scan still runs over the result, because people paste keys into chat. It is
defense in depth, NOT a clearance: it finds issuer-formatted tokens and nothing else.

Usage:
    distill_transcript.py [SESSION_ID] [--out PATH] [--raw DIR] [--strict]

    SESSION_ID   defaults to $CLAUDE_CODE_SESSION_ID (set by Claude Code in-session).
    --out PATH   where to write the markdown (default: stdout).
    --raw DIR    also copy the untouched .jsonl here (gitignore it -- it holds tool output).
    --strict     exit 1 instead of redacting if a known-shape secret is found.

Stdlib only. No deps.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

TOOL_VERSION = "0.2"

CONFIG_NAME = "okf.conf"
MODES = ("off", "local", "shared")
DEFAULT_MODE = "local"  # safe by default: keep the conversation, but never publish it

# Blocks we keep. Everything else -- tool_result, tool_use, thinking, images -- is dropped by type.
KEPT_BLOCK_TYPES = {"text"}

# Injected by hooks/harness into user turns; not typed by the human, and noisy.
_INJECTED = re.compile(
    r"<(system-reminder|persisted-output|command-name|command-message|command-args|local-command-stdout)>"
    r".*?</\1>",
    re.DOTALL,
)

# Issuer-formatted secrets: fixed prefix + charset + length. High confidence, low false-positive.
# This list is deliberately NOT extended with entropy heuristics -- transcripts are full of UUIDs,
# commit SHAs and base64, so entropy scoring here is a false-positive swamp.
SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("OpenAI API key", re.compile(r"\bsk-(?!ant-)[A-Za-z0-9]{20,}")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}")),
    ("Stripe live key", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{20,}")),
    ("GitLab PAT", re.compile(r"\bglpat-[0-9A-Za-z_-]{20,}")),
    ("npm token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("DigitalOcean token", re.compile(r"\bdop_v1_[a-f0-9]{64}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]

# What the scan provably cannot see. Printed every run so "no hits" is never read as "safe".
SCAN_BLIND_SPOTS = (
    "unknown-shape secrets are NOT detectable here: passwords, connection strings, PII, "
    "internal hostnames, private URLs, proprietary data. Read the file before committing."
)


def find_config(start: Path | None = None) -> Path | None:
    """Walk up from `start` looking for ai/okf.conf."""
    d = (start or Path.cwd()).resolve()
    for cand in [d, *d.parents]:
        p = cand / "ai" / CONFIG_NAME
        if p.is_file():
            return p
    return None


def read_mode(cfg: Path | None) -> str:
    """Read `archive = off|local|shared`. Absent/garbled config falls back to the SAFE mode.

    Fails safe on purpose: a typo must never silently upgrade a project to publishing its
    conversations. The cost of guessing wrong toward `local` is a citation that only resolves on
    one machine. The cost of guessing wrong toward `shared` is a public transcript.
    """
    if not cfg or not cfg.is_file():
        return DEFAULT_MODE
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_MODE
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" not in line:
            continue
        k, v = (x.strip().lower() for x in line.split("=", 1))
        if k == "archive":
            return v if v in MODES else DEFAULT_MODE
    return DEFAULT_MODE


def is_gitignored(path: Path) -> bool | None:
    """True/False, or None when git can't answer (no git, not a repo).

    `git check-ignore` matches patterns, so this works on a path that doesn't exist yet -- the
    check can run BEFORE anything is written.
    """
    try:
        r = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            capture_output=True,
            cwd=str(Path.cwd()),
        )
    except (FileNotFoundError, OSError):
        return None
    if r.returncode == 0:
        return True
    if r.returncode == 1:
        return False
    return None  # 128: not a git repo


def find_transcript(session_id: str, projects_dir: Path | None = None) -> Path | None:
    """Locate <session_id>.jsonl under ~/.claude/projects/.

    Globs on the session UUID rather than deriving the project dir name from cwd. Claude Code
    mangles the cwd (every non-alphanumeric char -> '-'), which differs between a Windows path
    and its git-bash view of the same directory; the UUID is unambiguous on every platform.
    """
    root = projects_dir or (Path.home() / ".claude" / "projects")
    if not root.is_dir():
        return None
    hits = sorted(root.glob(f"*/{session_id}.jsonl"))
    return hits[0] if hits else None


def scan_secrets(text: str) -> list[tuple[str, str]]:
    """Return [(label, matched_text)] for issuer-formatted secrets. Precision, not recall."""
    found: list[tuple[str, str]] = []
    for label, pat in SECRET_PATTERNS:
        for m in pat.finditer(text):
            found.append((label, m.group(0)))
    return found


def redact(text: str) -> tuple[str, list[tuple[str, str]]]:
    hits = scan_secrets(text)
    for label, raw in hits:
        text = text.replace(raw, f"[REDACTED: {label}]")
    return text, hits


def _clean(text: str) -> str:
    return _INJECTED.sub("", text).strip()


def extract_turns(lines: list[str]) -> list[dict]:
    """Pull human + assistant prose out of the JSONL.

    The load-bearing subtlety: a `tool_result` block carries role == "user". Filtering turns by
    role alone would archive every command's output -- exactly the content this tool exists to
    leave behind. Blocks are selected by TYPE (text), never by role.
    """
    turns: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("isSidechain"):  # subagent side-conversation, not the operator's thread
            continue
        msg = d.get("message") or {}
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content")
        parts: list[str] = []
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") in KEPT_BLOCK_TYPES:
                    parts.append(str(b.get("text", "")))
        text = _clean("\n".join(p for p in parts if p))
        if text:
            turns.append({"role": role, "text": text, "ts": d.get("timestamp", "")})
    return turns


def render(turns: list[dict], session_id: str, transcript: Path, today: str) -> str:
    day = (turns[0]["ts"][:10] if turns and turns[0].get("ts") else today) or today
    speaker = {"user": "Human", "assistant": "Claude"}
    out = [
        "---",
        f"session: {session_id}",
        f"distilled: {today}",
        f"transcript: {transcript.name}",
        "contains: human + assistant prose only",
        "excluded: tool results, tool calls, reasoning (dropped by block type, not by filtering)",
        "---",
        "",
        f"# Session {session_id[:8]} — {day}",
        "",
        "Verbatim conversation, for citing as `source:` from a memory note. Tool output was never",
        "included, so this is not a complete record of what ran — only of what was said.",
        "",
    ]
    for t in turns:
        stamp = f" · {t['ts'][11:16]}" if len(t.get("ts") or "") >= 16 else ""
        out.append(f"## {speaker[t['role']]}{stamp}")
        out.append("")
        out.append(t["text"])
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Distill a Claude Code transcript into citable markdown.")
    ap.add_argument("session_id", nargs="?", default=os.environ.get("CLAUDE_CODE_SESSION_ID"))
    ap.add_argument("--out", help="write markdown here (default: stdout)")
    ap.add_argument("--raw", help="also copy the untouched .jsonl into this dir (gitignore it)")
    ap.add_argument("--strict", action="store_true", help="exit 1 on a secret hit instead of redacting")
    ap.add_argument("--mode", choices=MODES, help="override ai/okf.conf `archive` for this run")
    ap.add_argument("--version", action="store_true")
    a = ap.parse_args(argv)

    if a.version:
        print(f"distill_transcript {TOOL_VERSION}")
        return 0

    cfg = find_config()
    mode = a.mode or read_mode(cfg)
    where = cfg if cfg else "(no ai/okf.conf — using safe default)"

    # `off` is a legitimate choice, not a failure: some projects must never keep a conversation.
    if mode == "off":
        print(f"distill: archive = off in {where} — not archiving this session.\n"
              "  Notes written now cannot cite a transcript; record decisions in prose and expect\n"
              "  `--check` to flag the missing source. Change with: archive = local")
        return 0

    # The guard that makes `local` mean local. Checked BEFORE writing: a transcript that was never
    # written to a committable path cannot be committed by accident. This is enforced by git's own
    # ignore rules rather than by remembering to be careful.
    if a.out and mode == "local":
        ig = is_gitignored(Path(a.out))
        if ig is False:
            print(f"distill: REFUSING to write {a.out}\n"
                  f"  archive = local (from {where}) means the conversation stays on this machine,\n"
                  f"  but that path is NOT gitignored — writing there risks committing it.\n"
                  f"  Fix: add 'ai/session/raw/' to .gitignore (re-run /init-ai-workspace), or\n"
                  f"  choose 'archive = shared' if you truly intend to commit conversations.",
                  file=sys.stderr)
            return 1
        if ig is None:
            print("distill: not a git repo (or git unavailable) — cannot verify the archive is "
                  "ignored. Nothing will be committed from here, but check before you add a remote.",
                  file=sys.stderr)

    if not a.session_id:
        print("distill: no session id (pass one, or run inside Claude Code where "
              "$CLAUDE_CODE_SESSION_ID is set).", file=sys.stderr)
        return 2

    src = find_transcript(a.session_id)
    if not src:
        print(f"distill: no transcript for {a.session_id} under ~/.claude/projects/.\n"
              f"  If this session is older than `cleanupPeriodDays` (default 30) Claude Code has "
              f"already pruned it — the conversation is gone and cannot be recovered.",
              file=sys.stderr)
        return 1

    lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
    turns = extract_turns(lines)
    if not turns:
        print(f"distill: {src.name} held no human/assistant prose.", file=sys.stderr)
        return 1

    today = date.today().isoformat()
    body = render(turns, a.session_id, src, today)
    body, hits = redact(body)

    if hits and a.strict:
        for label, _ in hits:
            print(f"distill: {label} found — refusing to write (--strict).", file=sys.stderr)
        return 1

    if a.out:
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding="utf-8")
        n_h = sum(1 for t in turns if t["role"] == "user")
        print(f"distill: wrote {out} ({len(body)/1024:.1f} KB, {len(turns)} turns / {n_h} human) "
              f"from {src.stat().st_size/1024:.0f} KB raw")
    else:
        sys.stdout.write(body)

    if a.raw:
        dest = Path(a.raw) / src.name
        # Unconditional, mode-independent: the raw transcript holds every tool result (env dumps,
        # file contents, command stdout). There is no project for which committing it is correct,
        # so refuse rather than warn — a warning scrolls past, a refusal doesn't.
        if is_gitignored(dest) is False:
            print(f"distill: REFUSING to copy the raw transcript to {dest} — that path is NOT\n"
                  f"  gitignored. The .jsonl holds every tool result: environment dumps, file\n"
                  f"  contents, command output. Add 'ai/session/raw/*.jsonl' to .gitignore first\n"
                  f"  (re-run /init-ai-workspace). The distilled .md was still written.",
                  file=sys.stderr)
            return 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        print(f"distill: copied raw transcript to {dest} (gitignored; holds tool output).")

    for label, _ in hits:
        print(f"distill: REDACTED {label} from the distilled output.", file=sys.stderr)
    print(f"distill: secret scan found {len(hits)} known-shape hit(s); {SCAN_BLIND_SPOTS}",
          file=sys.stderr)

    if mode == "shared" and a.out:
        print("distill: archive = shared — this transcript is COMMITTABLE and will be pushed with\n"
              "  the repo. Read it first. Anything said in the session is in it: client names,\n"
              "  unreleased plans, personal details, a key someone pasted into chat. If this repo\n"
              "  is public, that becomes public permanently — git history keeps it after deletion,\n"
              "  and forks and caches keep it after that.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
