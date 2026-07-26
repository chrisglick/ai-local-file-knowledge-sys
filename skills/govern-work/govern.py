#!/usr/bin/env python3
"""govern-work engine (Wave 1 / ENGINE CORE) -- the enforcement layer next to okf_normalize.py.

This module deliberately does NOT import okf_normalize.py. Both live as sibling skill dirs when
installed (~/.claude/skills/govern-work, ~/.claude/skills/init-ai-workspace), but govern.py must
survive a repo/install where init-ai-workspace is absent or a different version (R15: "the shipped
skill must survive a repo that has nothing"). So the tiny slice of OKF frontmatter handling this
file needs (parse/serialize, KEY_ORDER) is duplicated here, kept deliberately in sync by hand --
see NOTE FOR THE NEXT AGENT at the bottom of the module docstring in the Wave 1 report.

Verbs shipped so far (mint/verify/land/abort and hooks/ are a later wave; not touched here):

  govern.py --open "<question>"                file a type: open-question note (undecided fork)
  govern.py --rule <note.md> --verbatim "<t>"   close an open-question into a type: decision note
  govern.py --lint-spec <file.md>               R5 sizing guards + R14 underspecification guards
  govern.py --ratchet                           exit 1 if any tracked count ROSE above baseline
  govern.py --baseline                          rewrite the baseline file, DOWNWARD ONLY
  govern.py --drift                             surface decision-shaped session turns with no note
  govern.py --gate                              composite: okf --gate + --drift + --ratchet

Deps: pyyaml only (stdlib otherwise). Bundle defaults to ai/memory; config to ai/okf.conf, both
resolved by walking up from the bundle (or cwd) looking for a git root, mirroring
distill_transcript.py's find_config().
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

TOOL_VERSION = "0.1"

# Same key order okf_normalize.py uses, so a note this tool writes needs zero --apply pass to be
# canonical. Kept in sync BY HAND with okf_normalize.KEY_ORDER (see module docstring).
KEY_ORDER = ["type", "title", "description", "resource", "tags",
             "timestamp", "created", "valid_as_of", "source", "status",
             "verified_on", "relations"]

RELATION_VERBS = {"supersedes", "extends", "refines", "contradicts", "relates", "duplicates"}

# okf_normalize.py's TYPE_ENUM (v0.8) does NOT include "open-question" -- see the DECISION note in
# the Wave 1 report. We write it anyway because the brief is explicit about the literal value; this
# means `okf --check` / `okf --gate` will show one non-fatal "outside our enum (allowed by OKF)"
# line per open-question note, forever, until okf_normalize.py's TYPE_ENUM is extended (out of this
# wave's scope: the hard constraint forbids editing that file). Flagged prominently in the report.
OPEN_QUESTION_TYPE = "open-question"
DECISION_TYPE = "decision"

CONFIG_NAME = "okf.conf"
DEFAULT_BUNDLE = "ai/memory"
DEFAULT_BASELINE = "ai/govern-baseline.json"
# Source cited on notes gov writes when the caller doesn't pass --source. Points at the shim (which
# ships INTO the repo, unlike the skill's own install path) so the provenance check's path-exists
# scan has something real to resolve -- see report Decisions for why this, not a session archive.
DEFAULT_NOTE_SOURCE = "ai/scripts/gov"

_FM_DELIM = "---"
_HEADING2 = re.compile(r"^##\s+(.+?)\s*$")
_BULLET = re.compile(r"^\s*[-*]\s+(.+?)\s*$")
_LANE_LINE = re.compile(r"^\s*Lane:\s*(\S.*?)\s*$", re.IGNORECASE)
_REPORT_LINE = re.compile(r"^\s*Report:\s*(\S.*?)\s*$", re.IGNORECASE)
_BACKTICK_PATH = re.compile(r"`([^`\s][^`]*[/\\][^`]*)`")
_MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
_OVERRIDE_BULLET = re.compile(r"^\s*[-*]\s+(\w+)\s*:\s*(.+?)\s*$")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_PLACEHOLDER_MARKERS = ("todo", "placeholder", "tbd", "<", "fill in", "xxx")
# Sentinel a spec author left behind if they minted straight from the template file without
# deleting its instructional header comment (see _TEMPLATE-contract.template.md's own first line).
# Checked as a literal substring, not a regex, so it survives edits to the surrounding prose.
_TEMPLATE_HEADER_SENTINEL = "DELETE-THIS-COMMENT-BLOCK-BEFORE-MINTING"
# Heuristic-shaped bullets a `## Done when` line should NOT reduce to (R14: "checkable-shaped").
_VAGUE_DONE_WHEN = {"it works", "works", "done", "good", "complete", "finished", "works well", "it's done"}


def _safe_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def find_git_root(start: Path) -> Path | None:
    p = start.resolve()
    for cand in [p, *p.parents]:
        if (cand / ".git").exists():
            return cand
    return None


def find_config(start: Path | None = None) -> Path | None:
    """Walk up from `start` looking for ai/okf.conf (mirrors distill_transcript.find_config)."""
    d = (start or Path.cwd()).resolve()
    for cand in [d, *d.parents]:
        p = cand / "ai" / CONFIG_NAME
        if p.is_file():
            return p
    return None


def read_conf(cfg: Path | None) -> dict[str, str]:
    """Flat `key = value` reader for ai/okf.conf.

    Deliberately NOT the same case-folding as distill_transcript.read_mode(): that function
    lower-cases both key AND value because its one key (`archive`) is a closed enum. govern's keys
    hold paths, shell commands, and regexes -- lower-casing the value would corrupt all three. Only
    the key is folded to lowercase; the value is returned exactly as written after stripping an
    unescaped trailing `#`-comment and surrounding whitespace.
    """
    out: dict[str, str] = {}
    if not cfg or not cfg.is_file():
        return out
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip().lower()] = v.strip()
    return out


# --------------------------------------------------------------------------- OKF frontmatter (dup)

def parse_frontmatter(text: str):
    """Return (fm_dict_or_None, body). Duplicated from okf_normalize.py -- see module docstring."""
    if text.startswith("﻿"):
        text = text[1:]
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FM_DELIM:
        return None, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _FM_DELIM:
            end = i
            break
    if end is None:
        return None, text
    try:
        fm = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError:
        return None, text
    if not isinstance(fm, dict):
        return None, text
    body = "\n".join(lines[end + 1:])
    if body.startswith("\n"):
        body = body[1:]
    return fm, body


def serialize(fm: dict, body: str) -> str:
    ordered = {k: fm[k] for k in KEY_ORDER if k in fm}
    for k in fm:
        if k not in ordered:
            ordered[k] = fm[k]
    fm_text = yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True).rstrip()
    if not body.endswith("\n"):
        body += "\n"
    return f"{_FM_DELIM}\n{fm_text}\n{_FM_DELIM}\n\n{body}"


def slugify(text: str, *, max_words: int = 8) -> str:
    """Question/ruling text -> a filename-safe slug. Not fancy: lower, strip punctuation, hyphenate."""
    words = re.findall(r"[A-Za-z0-9]+", text.lower())[:max_words]
    slug = "-".join(words) or "untitled"
    return slug[:80]


def write_note(bundle: Path, *, type_: str, slug: str, title: str, description: str, body: str,
               source: str, status: str, relations: list[str] | None = None,
               timestamp: str | None = None) -> Path:
    """Write a new OKF-shaped note. Refuses to clobber an existing file at the target path."""
    bundle.mkdir(parents=True, exist_ok=True)
    filename = f"{type_}_{slug}.md"
    path = bundle / filename
    n = 2
    while path.exists():  # never silently overwrite; disambiguate instead
        path = bundle / f"{type_}_{slug}-{n}.md"
        n += 1
    ts = timestamp or now_iso()
    fm = {
        "type": type_,
        "title": title,
        "description": description,
        "timestamp": ts,
        "created": ts.split("T")[0],
        "source": source,
        "status": status,
    }
    if relations:
        fm["relations"] = relations
    path.write_text(serialize(fm, body), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- --open

def cmd_open(args) -> int:
    question = (args.open or "").strip()
    if not question:
        print("gov --open: refused -- the question text is empty. Pass the fork as a quoted "
              "string: gov --open \"should X use Y or Z?\"", file=sys.stderr)
        return 1
    bundle = Path(args.bundle)
    slug = slugify(question)
    body = (
        f"{question}\n\n"
        "Nobody has decided this yet. Close it with:\n"
        f"  gov --rule <this-note-path> --verbatim \"<the human's own words>\"\n\n"
        "**Verify:** n/a -- this note records an unresolved fork, not a checkable fact.\n"
    )
    path = write_note(
        bundle, type_=OPEN_QUESTION_TYPE, slug=slug, title=question[:80],
        description=question[:140], body=body,
        source=args.source or DEFAULT_NOTE_SOURCE, status="open",
    )
    print(f"filed open-question note: {path}")
    print("nobody has decided this -- close it later with `gov --rule` once a human rules on it.")
    return 0


# --------------------------------------------------------------------------- --rule

# R7's anti-re-adjudication heuristic: refuse an obviously-paraphrased ruling. A paraphrase tends
# to describe the ACT of deciding ("it was decided that...", "we agreed to...") rather than quote
# the decision itself. If that meta-phrasing is present AND there's no quote marker anywhere in the
# text, treat it as a summary, not a verbatim capture, and refuse. This is a heuristic, not a
# grammar -- it will occasionally refuse a fine ruling that happens to start "we decided" with no
# quotes; the fix in that case is to quote the human's own words, which is the point.
_META_PARAPHRASE = re.compile(
    r"\b(decided that|it was decided|we agreed to|agreed to use|the team decided|"
    r"was decided upon|has been decided)\b", re.IGNORECASE)
_QUOTE_MARKS = ('"', "'", "“", "‘", "`")


def _looks_paraphrased(text: str) -> bool:
    if _META_PARAPHRASE.search(text) and not any(q in text for q in _QUOTE_MARKS):
        return True
    return False


def cmd_rule(args) -> int:
    verbatim = args.verbatim if args.verbatim is not None else ""
    verbatim = verbatim.strip()
    if not verbatim:
        print("gov --rule: refused -- --verbatim is empty. Quote the human's own words, dated; "
              "an empty ruling closes nothing.", file=sys.stderr)
        return 1
    if _looks_paraphrased(verbatim):
        print("gov --rule: refused -- this reads like a PARAPHRASE of a ruling ('decided that...' "
              "/ 'agreed to...' with no quote marks), not the human's own words. R7's whole point "
              "is that a paraphrase invites re-litigation. Quote the ruling verbatim, e.g.:\n"
              '  --verbatim \'"ok ADR in okf."\'', file=sys.stderr)
        return 1
    note_path = Path(args.rule)
    if not note_path.is_file():
        print(f"gov --rule: refused -- no such note: {note_path}", file=sys.stderr)
        return 1
    text = note_path.read_text(encoding="utf-8")
    fm, _body = parse_frontmatter(text)
    if fm is None or str(fm.get("type") or "") != OPEN_QUESTION_TYPE:
        print(f"gov --rule: refused -- {note_path} is not a `type: {OPEN_QUESTION_TYPE}` note. "
              "--rule only closes an open question; point it at the note --open filed.",
              file=sys.stderr)
        return 1

    bundle = note_path.parent
    stem = note_path.stem
    slug = stem[len(OPEN_QUESTION_TYPE) + 1:] if stem.startswith(OPEN_QUESTION_TYPE + "_") else stem
    date = today_iso()
    name = args.name or "Krishna"
    title = str(fm.get("title") or slug)
    rel_to_open = Path(note_path.name)  # relative link within the same bundle dir

    # Body extends the existing `Decision (NAME, DATE)` / `Why` / `Supersedes` triad (per
    # KNOWLEDGE-SYSTEM.md) toward an ADR shape by adding `Status`, per R2's sealed ruling: this is
    # the SAME template, not a competing second one.
    body = (
        f"## Decision ({name}, {date})\n\n"
        f"{verbatim}\n\n"
        "## Why\n\n"
        f"Closes the open question in [{title}]({rel_to_open.as_posix()}).\n\n"
        "## Status\n\n"
        "Accepted\n\n"
        "## Supersedes\n\n"
        f"- {rel_to_open.as_posix()}\n\n"
        "**Verify:** re-read this note; the ruling above is quoted verbatim, not summarized.\n"
    )
    path = write_note(
        bundle, type_=DECISION_TYPE, slug=slug, title=title,
        description=f"Decision closing: {title}"[:140], body=body,
        source=args.source or DEFAULT_NOTE_SOURCE,
        # NOT status: verified -- that value is reserved for a human's own later promotion pass
        # (okf_normalize's own convention: "no tool ever writes this"), even though the ruling
        # itself is a direct human quote. The tool wrote the FILE; a human should still confirm it.
        status="unverified",
        relations=[f"supersedes {rel_to_open.as_posix()}"],
        timestamp=f"{date}T00:00:00Z",
    )
    print(f"filed decision note: {path}")
    print(f"  supersedes: {note_path}")

    # Close the open-question note itself -- a reader who opens IT directly (not via index.md or
    # the decision note) must see it's resolved, not "status: open" / "nobody has decided this yet"
    # forever. This is exactly the "confidently wrong, stale note" failure mode the project's own
    # README calls out as the one real net-negative of a note-based system -- --rule closing a
    # question must not itself create one.
    _close_open_question(note_path, fm, _body, closed_by=path)
    print(f"  closed: {note_path} (status: open -> closed)")
    return 0


def _close_open_question(note_path: Path, fm: dict, body: str, *, closed_by: Path) -> None:
    """Rewrite an open-question note in place once `--rule` supersedes it: status -> closed, body
    gets an unmissable CLOSED marker pointing at the decision note that resolved it. Keeps the
    original question text intact above the marker (still useful context)."""
    # Both notes always live in the same flat bundle dir (write_note never nests) -- a bare
    # filename is the correct, always-resolvable relative link, same convention `cmd_rule` already
    # uses for the decision note's own `supersedes <rel_to_open>` relation.
    rel_decision = closed_by.name
    marker = "Nobody has decided this yet."
    question = body.split(marker, 1)[0].strip() if marker in body else body.strip()
    new_body = (
        f"{question}\n\n"
        f"**CLOSED.** Superseded by decision: [{fm.get('title') or closed_by.stem}]"
        f"({rel_decision}).\n\n"
        "**Verify:** n/a -- this note recorded a fork that has since been closed; read the linked "
        "decision note above for the ruling, not this file.\n"
    )
    new_fm = dict(fm)
    new_fm["status"] = "closed"
    relations = list(new_fm.get("relations") or [])
    # "relates" (not a made-up "superseded-by") -- RELATION_VERBS in okf_normalize.py is a closed
    # enum and `okf --check --strict` warns (== fails) on any verb outside it. The decision note
    # already carries the authoritative directional `supersedes <this-note>` relation; this side
    # only needs a valid, resolvable pointer back, which the body's markdown link also carries in
    # human-readable form.
    closes_rel = f"relates {rel_decision}"
    if closes_rel not in relations:
        relations.append(closes_rel)
    new_fm["relations"] = relations
    note_path.write_text(serialize(new_fm, new_body), encoding="utf-8")


# --------------------------------------------------------------------------- --lint-spec

class LintResult:
    def __init__(self):
        self.fatals: list[str] = []
        self.overrides: list[str] = []

    def fatal(self, msg: str):
        self.fatals.append(msg)

    @property
    def ok(self) -> bool:
        return not self.fatals


def _headings(lines: list[str]) -> list[tuple[str, int]]:
    out = []
    for i, line in enumerate(lines):
        m = _HEADING2.match(line)
        if m:
            out.append((m.group(1), i))
    return out


def _section_lines(lines: list[str], headings: list[tuple[str, int]], name: str) -> list[str] | None:
    for idx, (h, start) in enumerate(headings):
        if h == name:
            end = headings[idx + 1][1] if idx + 1 < len(headings) else len(lines)
            return lines[start + 1:end]
    return None


def _bullets(section: list[str]) -> list[str]:
    return [m.group(1) for line in section if (m := _BULLET.match(line))]


def _overrides_in(lines: list[str], headings: list[tuple[str, int]]) -> dict[str, str]:
    section = _section_lines(lines, headings, "Overrides")
    out: dict[str, str] = {}
    if section is None:
        return out
    for line in section:
        m = _OVERRIDE_BULLET.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _resolve_claude_md(spec_path: Path) -> Path | None:
    root = find_git_root(spec_path.parent) or spec_path.parent
    cand = root / "CLAUDE.md"
    return cand if cand.is_file() else None


def _check_verify_expectation(spec_path: Path, result: LintResult) -> None:
    claude_md = _resolve_claude_md(spec_path)
    if claude_md is None:
        root = find_git_root(spec_path.parent) or spec_path.parent
        result.fatal(
            f"no CLAUDE.md found at {root} -- the spec's verify expectation can't be resolved "
            "from anywhere. Add a CLAUDE.md with a `## Verify` section naming one concrete, "
            "copy-pasteable command before minting specs against this project."
        )
        return
    text = claude_md.read_text(encoding="utf-8")
    lines = text.splitlines()
    headings = _headings(lines)
    verify_heading = next((h for h, _ in headings if "verify" in h.lower()), None)
    if verify_heading is None:
        result.fatal(
            f"{claude_md} has no `## Verify...` section -- add one naming the single blessed "
            "verify command this project trusts (see govern-work docs for the shape)."
        )
        return
    section = _section_lines(lines, headings, verify_heading)
    joined = "\n".join(section or []).strip()
    # HTML comments in this section are instructional scaffolding (the shipped template's own
    # explanation of what to fill in, plus its required trailing `<!-- /govern-work -->` structural
    # marker) -- never part of the operator's actual verify content. Strip them before scanning for
    # placeholder markers, otherwise a `<` inside ANY comment (including the template's own closing
    # marker, which has no heading after it and so always falls inside this section) would make the
    # check impossible to pass no matter what real command the operator fills in. This is the robust
    # fix (vs. reshaping the template) because it survives any future template edit that adds another
    # explanatory comment to this section.
    scannable = _HTML_COMMENT.sub("", joined).strip()
    if not scannable or any(m in scannable.lower() for m in _PLACEHOLDER_MARKERS):
        result.fatal(
            f"{claude_md}'s `## {verify_heading}` section is empty or a placeholder -- fill in one "
            "concrete, copy-pasteable verify command; `--lint-spec` refuses while it stands so a "
            "spec is never minted against an unverifiable project. (HTML comments in this section "
            "are ignored by this check -- only the real command/Expected text counts.)"
        )


def _check_template_header_left_in(spec_text: str, result: LintResult) -> None:
    """R14: a spec minted straight from the template file, header comment and all, produces a
    garbled multi-line path-existence refusal below (the header's own example backtick paths look
    like real references). Catch it directly, by name, before that guard even runs."""
    if _TEMPLATE_HEADER_SENTINEL in spec_text:
        result.fatal(
            "this spec still contains _TEMPLATE-contract.template.md's instructional header "
            f"comment (marked {_TEMPLATE_HEADER_SENTINEL}) -- delete the whole `<!-- ... -->` "
            "block at the top of the file before minting. It's instructions for writing the spec, "
            "not part of the spec itself, and its own example paths will otherwise be mistaken for "
            "real references by the path-existence guard below."
        )


def _check_paths_exist(spec_path: Path, lines: list[str], result: LintResult) -> None:
    root = find_git_root(spec_path.parent) or spec_path.parent
    candidates: set[str] = set()
    # HTML comments are instructional, never scanned for real content (same principle as the Verify
    # placeholder check above) -- so a stray comment's own example paths never garble this guard's
    # output, template header or otherwise.
    text = _HTML_COMMENT.sub("", "\n".join(lines))
    for m in _BACKTICK_PATH.finditer(text):
        candidates.add(m.group(1))
    for m in _MD_LINK.finditer(text):
        target = m.group(1)
        if "://" in target or not ("/" in target or target.endswith(".md")):
            continue
        candidates.add(target)
    for cand in sorted(candidates):
        clean = cand.split("#", 1)[0].strip()
        if not clean or clean.startswith(("http:", "https:")):
            continue
        p = Path(clean)
        resolved = p if p.is_absolute() else (root / clean)
        if not resolved.exists():
            result.fatal(
                f"referenced path does not exist: `{clean}` (resolved to {resolved}) -- fix the "
                "path or remove the reference before this spec is dispatched."
            )


def _check_report_declared(lines: list[str], headings: list[tuple[str, int]], result: LintResult) -> None:
    for line in lines:
        if _REPORT_LINE.match(line):
            return
    if any(h == "Report" for h, _ in headings):
        return
    result.fatal(
        "spec doesn't declare a report path -- add a line `Report: <path/to/report.md>` (or a "
        "`## Report` section) naming where the builder's completion report will be written."
    )


def lint_spec(spec_path: Path) -> LintResult:
    result = LintResult()
    text = spec_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    headings = _headings(lines)
    overrides = _overrides_in(lines, headings)

    # ---- R5: Goal singularity ----
    goal_headings = [h for h, _ in headings if h == "Goal"]
    goals_plural = [h for h, _ in headings if h == "Goals"]
    if goals_plural:
        result.fatal("`## Goals` (plural) is refused -- a spec states exactly one objective. "
                     "Rename to `## Goal` and split any second goal into its own spec.")
    elif not goal_headings:
        result.fatal("missing `## Goal` -- add exactly one `## Goal` section stating the single "
                     "objective this spec accomplishes.")
    elif len(goal_headings) > 1:
        result.fatal(f"found {len(goal_headings)} `## Goal` headings -- a spec may have exactly "
                     "one; split the extra goal(s) into separate specs.")

    # ---- R5: Done when (1-4 checkable bullets) ----
    done_section = _section_lines(lines, headings, "Done when")
    if done_section is None:
        result.fatal("missing `## Done when` -- add a `## Done when` section with 1-4 checkable "
                     "bullets (a command, a file, a specific behavior -- not a feeling).")
    else:
        bullets = _bullets(done_section)
        if not bullets:
            result.fatal("`## Done when` has no bullet items -- list 1-4 checkable outcomes as "
                         "`- ...` bullets.")
        elif len(bullets) > 4:
            result.fatal(f"`## Done when` has {len(bullets)} bullets -- the guard allows at most "
                         "4; split into a separate spec or drop non-essential checks.")
        for i, b in enumerate(bullets, 1):
            if len(b.split()) < 3 or b.strip().lower().rstrip(".") in _VAGUE_DONE_WHEN:
                result.fatal(f"`## Done when` bullet {i} ('{b}') doesn't read as a checkable "
                             "outcome -- rewrite as a concrete, verifiable statement.")

    # ---- R5: Deliverables (<= 4) ----
    deliverables_section = _section_lines(lines, headings, "Deliverables")
    if deliverables_section is not None:
        d_bullets = _bullets(deliverables_section)
        if len(d_bullets) > 4:
            result.fatal(f"`## Deliverables` lists {len(d_bullets)} items -- the guard allows at "
                         "most 4; split the spec.")

    # ---- R5: exactly one declared lane (override: AllowMixedLane) ----
    lane_values = []
    for line in lines:
        m = _LANE_LINE.match(line)
        if m:
            lane_values.append(m.group(1).strip())
    distinct_lanes = sorted(set(lane_values))
    if not lane_values:
        result.fatal("no `Lane: <name>` line found -- declare exactly one lane this spec touches, "
                     "e.g. `Lane: docs`.")
    elif len(distinct_lanes) > 1:
        if "AllowMixedLane" in overrides:
            result.overrides.append(
                f"OVERRIDE: AllowMixedLane -- {overrides['AllowMixedLane']} (lanes: {distinct_lanes})"
            )
        else:
            result.fatal(f"declares multiple lanes {distinct_lanes} -- a spec may declare exactly "
                         "one; split into one spec per lane, or add `## Overrides` with an "
                         "`AllowMixedLane: <reason>` bullet to override loudly.")

    # ---- R14: verify expectation resolvable from CLAUDE.md ----
    _check_verify_expectation(spec_path, result)

    # ---- R14: template's own instructional header wasn't left in (would garble the next check) ----
    _check_template_header_left_in(text, result)

    # ---- R14: every referenced path exists ----
    _check_paths_exist(spec_path, lines, result)

    # ---- R14: report path declared ----
    _check_report_declared(lines, headings, result)

    return result


def cmd_lint_spec(args) -> int:
    spec_path = Path(args.lint_spec)
    if not spec_path.is_file():
        print(f"gov --lint-spec: no such file: {spec_path}", file=sys.stderr)
        return 2
    result = lint_spec(spec_path)
    for line in result.overrides:
        print(line)  # LOUD, printed unconditionally -- an override is never a silent exception
    if result.fatals:
        print(f"REFUSED -- {spec_path} fails {len(result.fatals)} guard(s):")
        for msg in result.fatals:
            print(f"  ! {msg}")
        return 1
    print(f"OK -- {spec_path} passes all sizing + underspecification guards.")
    return 0


# --------------------------------------------------------------------------- --ratchet / --baseline

def _iter_text_files(root: Path):
    """Files tracked-ish for grep rules: everything under root except .git/ and common noise dirs."""
    skip_dirs = {".git", "node_modules", ".okf-backups", "__pycache__", ".pytest_cache"}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in skip_dirs for part in p.parts):
            continue
        yield p


def _read_text_or_none(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def count_unverified(bundle: Path) -> int:
    n = 0
    if not bundle.is_dir():
        return 0
    for md in bundle.rglob("*.md"):
        if md.name.lower() in ("index.md", "log.md"):
            continue
        text = _read_text_or_none(md)
        if text is None:
            continue
        fm, _ = parse_frontmatter(text)
        if fm and str(fm.get("status") or "").strip().lower() == "unverified":
            n += 1
    return n


def _grep_rules(conf: dict[str, str]) -> dict[str, str]:
    """`govern_ratchet_grep_<name> = <regex>` entries -> {name: pattern}."""
    out = {}
    for k, v in conf.items():
        if k.startswith("govern_ratchet_grep_"):
            out[k[len("govern_ratchet_grep_"):]] = v
    return out


def count_grep_rule(root: Path, pattern: str) -> int:
    try:
        rx = re.compile(pattern)
    except re.error as e:
        print(f"gov: bad govern_ratchet_grep pattern {pattern!r}: {e}", file=sys.stderr)
        return 0
    n = 0
    for p in _iter_text_files(root):
        text = _read_text_or_none(p)
        if text is None:
            continue
        n += len(rx.findall(text))
    return n


def compute_counts(bundle: Path, conf: dict[str, str], root: Path) -> dict[str, int]:
    counts = {"unverified_notes": count_unverified(bundle)}
    for name, pattern in _grep_rules(conf).items():
        counts[f"grep:{name}"] = count_grep_rule(root, pattern)
    return counts


def _baseline_path(conf: dict[str, str], root: Path) -> Path:
    rel = conf.get("govern_ratchet_baseline", DEFAULT_BASELINE)
    p = Path(rel)
    return p if p.is_absolute() else (root / rel)


def cmd_ratchet(args) -> int:
    bundle = Path(args.bundle)
    root = find_git_root(bundle) or Path.cwd()
    conf = read_conf(find_config(bundle))
    baseline_file = _baseline_path(conf, root)
    counts = compute_counts(bundle, conf, root)

    if not baseline_file.is_file():
        print(f"gov --ratchet: no baseline at {baseline_file} yet -- nothing to compare against.")
        print("Current counts:")
        for k, v in sorted(counts.items()):
            print(f"  {k}: {v}")
        print(f"Run `gov --baseline` to record these as the starting point (day-zero degrade, "
              "not a failure).")
        return 0

    try:
        baseline = json.loads(baseline_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"gov --ratchet: could not read baseline {baseline_file}: {e}", file=sys.stderr)
        return 2

    rose = []
    for k, v in counts.items():
        base_v = int(baseline.get(k, 0))
        if v > base_v:
            rose.append((k, base_v, v))

    print("Current counts:")
    for k, v in sorted(counts.items()):
        base_v = baseline.get(k, "(new)")
        print(f"  {k}: {v}  (baseline: {base_v})")

    if rose:
        print("\nRATCHET FAILED -- the following count(s) rose above their committed baseline:")
        for k, base_v, v in rose:
            print(f"  ! {k}: {base_v} -> {v} (+{v - base_v})")
        print("Nothing here asserts a count is zero -- only that it did not get worse. Fix the "
              "regression, or if the count is now genuinely, deliberately higher, earn it and run "
              "`gov --baseline` to record the new number (that command itself refuses to raise "
              "anything -- see its own help).")
        return 1
    print("\nRATCHET OK -- no tracked count rose above its baseline.")
    return 0


def cmd_baseline(args) -> int:
    bundle = Path(args.bundle)
    root = find_git_root(bundle) or Path.cwd()
    conf = read_conf(find_config(bundle))
    baseline_file = _baseline_path(conf, root)
    counts = compute_counts(bundle, conf, root)

    old: dict[str, int] = {}
    if baseline_file.is_file():
        try:
            old = json.loads(baseline_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"gov --baseline: could not read existing baseline {baseline_file}: {e}",
                  file=sys.stderr)
            return 2

    violations = []
    for k, v in counts.items():
        if k in old and v > int(old[k]):
            violations.append((k, int(old[k]), v))

    if violations:
        print("REFUSED -- --baseline rewrites DOWNWARD ONLY. The following count(s) would RISE, "
              "which is the same sin as editing the gate to make a run pass:")
        for k, old_v, new_v in violations:
            print(f"  ! {k}: {old_v} -> {new_v} (+{new_v - old_v}) -- refused")
        print(f"Baseline file NOT written: {baseline_file}")
        print("Fix the regression first, then re-run `gov --baseline` once every count is <= its "
              "current committed value.")
        return 1

    merged = dict(old)
    merged.update(counts)
    baseline_file.parent.mkdir(parents=True, exist_ok=True)
    baseline_file.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verb = "wrote" if not old else "updated"
    print(f"{verb} baseline -> {baseline_file}")
    for k, v in sorted(merged.items()):
        was = old.get(k)
        note = "" if was is None else (" (unchanged)" if was == v else f" (was {was})")
        print(f"  {k}: {v}{note}")
    return 0


# --------------------------------------------------------------------------- --drift
#
# THE FLAGSHIP FEATURE (brief SS5a). Reads ai/session/raw/*.md -- the distilled transcripts
# `distill_transcript.py` writes and `end-session` commits -- looking for DECISION-SHAPED HUMAN
# TURNS that have no matching `type: decision` note in ai/memory/. This is "capture is not
# automatic" made mechanical: the Reddit ledger-drift complaint this whole skill answers.
#
# R2 sealed design (brief SS9 open question 2): a deterministic regex heuristic engine here,
# favoring RECALL over precision -- a human/agent judgement pass (wired up in SKILL.md, not this
# file) triages the candidate list. A candidate that turns out not to be a real decision costs a
# few seconds of the judgement pass; a real decision this engine fails to flag costs nothing --
# it just silently repeats the exact failure mode the skill exists to fix. So when in doubt, flag.
#
# Traps this function must not fall into (brief SS7, doctrine pack SS1.4-1.5):
#   - The distilled corpus holds NO tool output BY DESIGN (`distill_transcript.py` drops
#     tool_result/tool_use/thinking by block TYPE, never by role). --drift must never assume
#     evidence -- benchmarks, command output, file contents -- is present in the corpus; it only
#     ever sees "what was said," never "what ran."
#   - `archive = local` (the default) gitignores ai/session/raw. A fresh clone of a `local`-mode
#     repo has zero session files not because none were ever run, but because they never left the
#     original machine. Reporting that as plain "no drift found" would be a lie by omission --
#     say so explicitly, distinguished from genuine day-zero.
#   - Day-zero (no corpus at all, ever) must explain and name the fix, never return a bare empty
#     result (R15).

_TURN_HEADING = re.compile(r"^##\s+(Human|Claude)(?:\s*·\s*(\d{1,2}:\d{2}))?\s*$")

# Candidates for where distilled sessions live. The doctrine pack (SS1.4) notes the session-dir
# spelling varies (`ai/session/` singular vs `ai/sessions/` plural) depending on what a given
# project already had before init ran -- do not hardcode one spelling.
_SESSION_DIR_RELS = ("ai/session/raw", "ai/sessions/raw")

# Deterministic regex heuristics over imperative/ruling phrasing (R2's "heuristic engine"). Each
# entry is deliberately broad -- this is a recall-favoring net, not a precision instrument. Every
# pattern is grounded in a real ruling-shape from the evidence corpus (R7's verbatim-quote
# doctrine, RRM/CCC's dated rulings, QLL's AGREEMENT rulings) rather than invented from nothing.
_DECISION_PATTERNS = [
    re.compile(r"\blet'?s\s+(use|go with|do|ship|switch|adopt|drop|kill|build|stick with|not)\b", re.I),
    re.compile(r"\bwe\s+(should|will|must|need to|are going to|'re going to)\b", re.I),
    re.compile(r"\b(go with|stick with|switch to|use)\s+\S+\s+(instead of|over|rather than|not)\b", re.I),
    re.compile(r"^\s*(yes|ok|okay|sure|agreed|fine|correct|right)\b[,.:]?\s+\S", re.I),
    re.compile(r"^\s*no[,.]\s+\S", re.I),
    re.compile(r"\bfrom now on\b", re.I),
    re.compile(r"\balways\b", re.I),
    re.compile(r"\bnever\b", re.I),
    re.compile(r"\bmust\s+(not\s+)?\w", re.I),
    re.compile(r"\b(decid(e|ed|ing)|rul(e|ing|ed)|seal(ed)?|settled?|final answer)\b", re.I),
    re.compile(r"\binstead\b", re.I),
    re.compile(r"\bi\s+(want|need|prefer)\b", re.I),
    re.compile(r"\b(don'?t|do not|stop)\s+(use|do|ship|build|touch)\b", re.I),
    re.compile(r"\bplease\s+(use|switch|change|make|always|never)\b", re.I),
    re.compile(r"^\s*(here'?s|that'?s)\s+(the|my)\s+(call|ruling|decision)\b", re.I),
]

# Words too common to carry topical meaning; kept short on purpose -- this is a recall net, not a
# linguistics project. Anything 3 chars or shorter is dropped separately (see _significant_words).
_STOPWORDS = {
    "that", "this", "with", "from", "have", "should", "would", "could", "will", "the", "and",
    "for", "are", "you", "your", "not", "but", "was", "were", "been", "into", "just", "like",
    "over", "than", "then", "also", "only", "some", "more", "most", "such", "each", "very",
    "let's", "lets", "please", "always", "never", "must", "instead", "want", "need", "prefer",
    "decided", "deciding", "decide", "ruling", "ruled", "rule", "sealed", "settled", "final",
    "here's", "that's", "call", "decision", "going", "stick",
}


def _significant_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", text.lower()) if len(w) > 3 and w not in _STOPWORDS}


def _split_sentences(text: str) -> list[str]:
    # Split on sentence-ish boundaries and newlines. A candidate sentence, not the whole turn, is
    # what gets flagged and printed -- the shorter the excerpt, the faster a human/agent judgement
    # pass can triage it.
    chunks = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'`])|\n+", text)
    return [c.strip() for c in chunks if c.strip()]


def parse_distilled_transcript(path: Path) -> tuple[dict, list[dict]]:
    """Return (frontmatter_dict, turns). Each turn: {role: 'Human'|'Claude', ts, text}.

    Mirrors distill_transcript.py's render() shape exactly (doctrine pack SS1.4): a plain
    key:value frontmatter block, then `## Human`/`## Claude` headings (optionally ` · HH:MM`),
    each followed by prose. Reuses this module's own OKF-shaped parse_frontmatter -- the
    frontmatter here is valid YAML even though the file is never treated as an OKF concept note.
    """
    text = _read_text_or_none(path)
    if text is None:
        return {}, []
    fm, body = parse_frontmatter(text)
    if fm is None:
        fm, body = {}, text
    lines = body.splitlines()
    turns: list[dict] = []
    cur_role = None
    cur_ts = None
    buf: list[str] = []

    def flush():
        if cur_role is not None:
            t = "\n".join(buf).strip()
            if t:
                turns.append({"role": cur_role, "ts": cur_ts, "text": t})

    for line in lines:
        m = _TURN_HEADING.match(line)
        if m:
            flush()
            cur_role, cur_ts, buf = m.group(1), m.group(2), []
        else:
            buf.append(line)
    flush()
    return fm, turns


class DriftCandidate:
    def __init__(self, session_file: Path, ts: str | None, sentence: str):
        self.session_file = session_file
        self.ts = ts
        self.sentence = sentence
        self.words = _significant_words(sentence)


def extract_candidates(session_file: Path, turns: list[dict]) -> list[DriftCandidate]:
    out = []
    for turn in turns:
        if turn["role"] != "Human":
            continue
        for sentence in _split_sentences(turn["text"]):
            if any(p.search(sentence) for p in _DECISION_PATTERNS):
                out.append(DriftCandidate(session_file, turn.get("ts"), sentence))
    return out


def load_decision_note_texts(bundle: Path) -> list[tuple[Path, str, set[str]]]:
    """[(path, timestamp, significant_words)] for every type: decision note in the bundle."""
    out = []
    if not bundle.is_dir():
        return out
    for md in bundle.rglob("decision_*.md"):
        text = _read_text_or_none(md)
        if text is None:
            continue
        fm, body = parse_frontmatter(text)
        if fm is None or str(fm.get("type") or "") != DECISION_TYPE:
            continue
        combined = " ".join(str(fm.get(k) or "") for k in ("title", "description")) + " " + body
        out.append((md, str(fm.get("timestamp") or fm.get("created") or ""), _significant_words(combined)))
    return out


def _newest_decision_timestamp(bundle: Path) -> str | None:
    ts_values = [ts for _, ts, _ in load_decision_note_texts(bundle) if ts]
    return max(ts_values) if ts_values else None


def candidate_is_documented(cand: DriftCandidate, decisions: list[tuple[Path, str, set[str]]]) -> Path | None:
    """Return the decision note path that appears to already cover this candidate, or None.

    Deliberately conservative (unlike candidate EXTRACTION, which favors recall): treating an
    undocumented decision as "already covered" hides real drift, which is the one failure mode
    that defeats the whole verb. Requires a real chunk of shared vocabulary, not one stray word.
    """
    if not cand.words:
        return None
    for path, _ts, words in decisions:
        shared = cand.words & words
        if len(shared) >= 3 or (len(shared) >= 1 and len(shared) / len(cand.words) >= 0.6):
            return path
    return None


def _is_gitignored(path: Path, cwd: Path) -> bool | None:
    """True/False, or None when git can't answer. Duplicated from distill_transcript.py's
    is_gitignored (small enough to keep in sync by hand; see module docstring on why govern.py
    doesn't import sibling-skill internals). `cwd` matters: git resolves ignore rules relative to
    the repo it's run inside, not the target path's own location."""
    try:
        r = subprocess.run(["git", "check-ignore", "-q", str(path)], capture_output=True, cwd=str(cwd))
    except (FileNotFoundError, OSError):
        return None
    if r.returncode == 0:
        return True
    if r.returncode == 1:
        return False
    return None


def _find_session_files(root: Path) -> tuple[list[Path], list[Path]]:
    """(existing_dirs, md_files) across every known session-dir spelling."""
    dirs = [root / rel for rel in _SESSION_DIR_RELS if (root / rel).is_dir()]
    files: list[Path] = []
    for d in dirs:
        files.extend(sorted(d.glob("*.md")))
    return dirs, files


def cmd_drift(args) -> int:
    bundle = Path(args.bundle)
    root = find_git_root(bundle) or Path.cwd()
    conf = read_conf(find_config(bundle))
    archive_mode = (conf.get("archive") or "local").strip().lower()
    if archive_mode not in ("off", "local", "shared"):
        archive_mode = "local"  # same fail-safe default distill_transcript.py uses

    dirs, files = _find_session_files(root)
    default_dir = root / _SESSION_DIR_RELS[0]

    if not dirs or not files:
        # --- day-zero / local-mode / off-mode: explain, never return a bare empty result (R15) ---
        if archive_mode == "off":
            print(f"gov --drift: archive = off -- sessions are never distilled by design in this "
                  f"project, so there is no corpus for --drift to read. This is not a failure; "
                  f"decisions made in un-archived sessions must be recorded by hand, via "
                  f"`gov --open` / `gov --rule`, or by switching `archive = local` in "
                  f"{find_config(bundle) or 'ai/okf.conf'}.")
            return 0
        # Probe a FILE path inside the candidate dir, not the dir itself: git only recognizes a
        # directory-only gitignore pattern (trailing slash, e.g. `ai/session/raw/`) against a path
        # it can confirm is a directory -- which it cannot for one that doesn't exist on disk. A
        # file path under that same prefix matches the pattern regardless of whether the file (or
        # even the directory) exists, so probing `.../raw/__gov_probe__.md` correctly detects the
        # ignore rule even when the whole directory is absent (the fresh-clone case this exists
        # for). Verified empirically -- do not "simplify" back to checking default_dir itself.
        ignored = _is_gitignored(default_dir / "__gov_probe__.md", root)
        if ignored:
            print(f"gov --drift: no session files found at {', '.join(str(d) for d in _SESSION_DIR_RELS)} "
                  f"in this checkout, and {default_dir} IS gitignored (archive = {archive_mode}, "
                  f"the default). That means EITHER no session has been distilled yet, OR sessions "
                  f"were distilled on a different machine and never left it -- `archive = local` "
                  f"gitignores the corpus by design, so a fresh clone always looks empty here even "
                  f"when the original machine's corpus is not. --drift cannot tell these apart from "
                  f"a checkout alone. If you expect history, check the machine that ran the "
                  f"sessions, or switch to `archive = shared` to commit the corpus.")
            return 0
        print(f"gov --drift: no session files found -- looked for *.md under "
              f"{', '.join(str(root / r) for r in _SESSION_DIR_RELS)} and found none. This looks "
              f"like day zero: no session has been distilled into this corpus yet (or "
              f"init-ai-workspace/distill_transcript.py has never been run here). Not a failure -- "
              f"drift earns its keep as session history accrues. Fix: run a session, then "
              f"`end-session` (or `okf --distill`) to produce the first ai/session/raw/<id>.md, "
              f"and re-run `gov --drift`.")
        return 0

    newest_dec_ts = _newest_decision_timestamp(Path(args.bundle))
    if newest_dec_ts:
        # Compare by the frontmatter's own `distilled:` date (YYYY-MM-DD) when present, else fall
        # back to file mtime -- both compared against the decision timestamp's date portion only
        # (decision timestamps are ISO-8601; session `distilled:` values are date-only).
        cutoff_date = newest_dec_ts[:10]
        kept = []
        for f in files:
            fm, _turns = parse_distilled_transcript(f)
            distilled = str(fm.get("distilled") or "")
            file_date = distilled[:10] if distilled else datetime.fromtimestamp(
                f.stat().st_mtime, tz=timezone.utc).date().isoformat()
            if file_date >= cutoff_date:
                kept.append(f)
        if not kept:
            print(f"gov --drift: {len(files)} session file(s) found, but none newer than the "
                  f"latest recorded decision ({newest_dec_ts}). Nothing new to check -- not a "
                  f"failure.")
            return 0
        files = kept

    decisions = load_decision_note_texts(Path(args.bundle))
    all_candidates: list[DriftCandidate] = []
    for f in files:
        _fm, turns = parse_distilled_transcript(f)
        all_candidates.extend(extract_candidates(f, turns))

    if not all_candidates:
        print(f"gov --drift: scanned {len(files)} session file(s), found zero decision-shaped "
              f"human turns. Either genuinely no rulings were made in these sessions, or the "
              f"heuristics missed the phrasing used -- see govern-work's docs for the pattern "
              f"list, and consider filing a gap.")
        return 0

    unmatched = []
    for cand in all_candidates:
        covered_by = candidate_is_documented(cand, decisions)
        if covered_by is None:
            unmatched.append(cand)

    print(f"gov --drift: scanned {len(files)} session file(s), {len(all_candidates)} "
          f"decision-shaped candidate(s), {len(decisions)} existing decision note(s) in "
          f"{args.bundle}.\n")

    if not unmatched:
        print("DRIFT CLEAN -- every decision-shaped candidate has a matching decision note.")
        return 0

    print(f"DRIFT FOUND -- {len(unmatched)} decision-shaped candidate(s) with NO matching "
          f"`decision_*.md` note (candidates are a HEURISTIC net -- favor recall; a human/agent "
          f"judgement pass should triage each before filing):\n")
    for i, cand in enumerate(unmatched, 1):
        try:
            rel = cand.session_file.relative_to(root)
        except ValueError:
            rel = cand.session_file
        stamp = f" · {cand.ts}" if cand.ts else ""
        print(f"  [{i}] {rel}{stamp}")
        print(f"      \"{cand.sentence}\"")
    print(f"\nEach candidate above has no `decision_*.md` note in {args.bundle} that shares "
          f"enough vocabulary to look like the same ruling. File the real ones with "
          f"`gov --open` + `gov --rule` (or confirm it's already covered elsewhere and move on).")
    return 1


# --------------------------------------------------------------------------- --gate

def find_okf_normalize() -> Path | None:
    """Locate the sibling init-ai-workspace skill's okf_normalize.py.

    govern-work must survive an install where init-ai-workspace is a different version or
    genuinely absent (R15) -- so this is a best-effort search, never an import, and a miss is
    reported as a named, fixable gap rather than a crash.
    """
    candidates = []
    env = os.environ.get("OKF_SKILL_DIR")
    if env:
        candidates.append(Path(env) / "okf_normalize.py")
    here = Path(__file__).resolve().parent
    candidates.append(here.parent / "init-ai-workspace" / "okf_normalize.py")
    candidates.append(Path.home() / ".claude" / "skills" / "init-ai-workspace" / "okf_normalize.py")
    for c in candidates:
        if c.is_file():
            return c
    return None


def run_okf_gate(bundle: Path) -> tuple[int | None, str]:
    """Run `okf_normalize.py <bundle> --gate` out of process. Returns (exit_code, combined output);
    exit_code is None when okf_normalize.py could not be located or run at all (distinct from a
    real nonzero exit -- see cmd_gate)."""
    okf_path = find_okf_normalize()
    if okf_path is None:
        return None, ("okf_normalize.py not found (tried $OKF_SKILL_DIR, the sibling "
                       "init-ai-workspace skill dir, and ~/.claude/skills/init-ai-workspace). "
                       "Install the init-ai-workspace skill, or set OKF_SKILL_DIR to where it "
                       "lives, then re-run `gov --gate`.")
    try:
        proc = subprocess.run(
            [sys.executable, str(okf_path), str(bundle), "--gate"],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"failed to run {okf_path} --gate: {e}"
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()


def cmd_gate(args) -> int:
    bundle = Path(args.bundle)
    failures: list[str] = []

    print("=== gov --gate: okf --gate + gov --drift + gov --ratchet ===\n")

    print("--- component: okf --gate ---")
    okf_rc, okf_out = run_okf_gate(bundle)
    print(okf_out or "(no output)")
    if okf_rc is None:
        failures.append(f"okf --gate -- could not run: {okf_out}")
    elif okf_rc != 0:
        failures.append(f"okf --gate (exit {okf_rc}) -- see its output above; run "
                         f"`okf {bundle} --gate` directly to reproduce, `okf {bundle} --apply` to "
                         f"auto-fix mechanical drift.")
    print()

    print("--- component: gov --drift ---")
    drift_rc = cmd_drift(args)
    if drift_rc != 0:
        failures.append(f"gov --drift (exit {drift_rc}) -- see the candidate list above; file the "
                         f"real ones with `gov --open` + `gov --rule`.")
    print()

    print("--- component: gov --ratchet ---")
    ratchet_rc = cmd_ratchet(args)
    if ratchet_rc != 0:
        failures.append(f"gov --ratchet (exit {ratchet_rc}) -- see the rise reported above; fix the "
                         f"regression or earn a new baseline with `gov --baseline`.")
    print()

    if failures:
        print(f"GATE FAILED -- {len(failures)} component(s) failed:")
        for f in failures:
            print(f"  ! {f}")
        return 1
    print("GATE OK -- okf --gate, gov --drift, and gov --ratchet are all clean.")
    return 0


# --------------------------------------------------------------------------- main

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="govern-work engine core: notes + lint-spec + ratchet.")
    ap.add_argument("bundle", nargs="?", default=DEFAULT_BUNDLE,
                     help=f"OKF bundle dir (default {DEFAULT_BUNDLE})")
    ap.add_argument("--open", metavar="QUESTION", help="file a type: open-question note")
    ap.add_argument("--rule", metavar="NOTE", help="close an open-question note into a decision")
    ap.add_argument("--verbatim", metavar="TEXT", help="the human's own words, for --rule")
    ap.add_argument("--name", metavar="NAME", help="who ruled (default: Krishna), for --rule")
    ap.add_argument("--source", metavar="PATH", help=f"note source (default: {DEFAULT_NOTE_SOURCE})")
    ap.add_argument("--lint-spec", metavar="FILE", help="run R5+R14 guards on a spec file")
    ap.add_argument("--ratchet", action="store_true", help="exit 1 if a tracked count rose")
    ap.add_argument("--baseline", action="store_true", help="rewrite baseline, downward only")
    ap.add_argument("--drift", action="store_true",
                     help="surface decision-shaped session turns with no matching decision note")
    ap.add_argument("--gate", action="store_true",
                     help="composite: okf --gate + gov --drift + gov --ratchet")
    ap.add_argument("--version", action="store_true", help="print tool version")
    return ap


CONTRACT_VERBS = {"mint", "verify", "land", "abort"}


def main(argv=None) -> int:
    _safe_stdio()
    raw = list(argv if argv is not None else sys.argv[1:])
    if raw and raw[0] in CONTRACT_VERBS:
        # Contract-runner verbs (Wave 3) live in a sibling module and use subcommand-style
        # parsing (mint/verify/land/abort each take genuinely different positional/option
        # shapes) rather than this module's flat-flag style -- see govern_contract.py's own
        # docstring for why. Imported lazily so a repo that never uses the contract runner pays
        # nothing for it.
        import govern_contract
        return govern_contract.main(raw)

    ap = build_parser()
    args = ap.parse_args(argv)

    if args.version:
        print(f"govern.py tool {TOOL_VERSION}")
        return 0
    if args.open is not None:
        return cmd_open(args)
    if args.rule is not None:
        if args.verbatim is None:
            print("gov --rule: --verbatim is required.", file=sys.stderr)
            return 2
        return cmd_rule(args)
    if args.lint_spec is not None:
        return cmd_lint_spec(args)
    if args.ratchet:
        return cmd_ratchet(args)
    if args.baseline:
        return cmd_baseline(args)
    if args.drift:
        return cmd_drift(args)
    if args.gate:
        return cmd_gate(args)

    ap.error("no verb given -- one of --open/--rule/--lint-spec/--ratchet/--baseline/--drift/--gate")
    return 2  # unreachable; ap.error() exits


if __name__ == "__main__":
    raise SystemExit(main())
