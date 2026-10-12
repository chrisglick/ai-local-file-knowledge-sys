#!/usr/bin/env python3
"""lk-audit-knowledge engine: find surplus, duplicate, stale and low-information notes in an OKF
bundle, write an editable triage plan, and apply a plan that a human approved.

  audit_knowledge.py [BUNDLE]                  read-only report, grouped by finding kind (exit 0)
  audit_knowledge.py [BUNDLE] --json           the same findings, plus suggested plan rows, as JSON
  audit_knowledge.py [BUNDLE] --plan OUT.md    write an editable triage plan (one table row per note)
  audit_knowledge.py [BUNDLE] --apply PLAN.md  execute an approved plan: delete and deprecate here;
                                               merge-into and promote are printed for a person to do

This is a heuristic engine. It surfaces candidates; the running agent judges every one and a human
approves the plan before --apply (SKILL.md, "The audit workflow"). Every threshold is a constant
below, so a bundle that needs different numbers changes one line.

Self-contained on purpose: it duplicates the small frontmatter slice it needs instead of importing
okf_normalize.py, so it survives an install where lk-init-ai-workspace is absent or a different
version. It reads BOTH vocabularies because bundles will be mid-migration:
legacy (`source`, `timestamp`, `status: unverified|verified|stale|open|closed`) and OKF v0.2
(`sources: [{resource}]`, `generated: {by, at}`, `status: draft|stable|deprecated`, `verified`,
`stale_after`). Deps: pyyaml only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import yaml

TOOL_VERSION = "1.0.0"
DEFAULT_BUNDLE = "ai/memory"

# --------------------------------------------------------------------------- thresholds

BURST_MIN_NOTES = 5             # notes of ONE type citing ONE first source, filed on ONE day
BURST_JUNK_SHARE = 0.5          # when this share of a burst is LOW_INFO, suggest deleting all of it
LOW_INFO_MIN_CHARS = 240        # body text left once frontmatter, Verify, headings, boilerplate go
LOW_INFO_PREFIX_CHARS = 60      # title and description sharing this many leading chars = an echo
LOW_INFO_ECHO_MIN_CHARS = 20    # ...but a title shorter than this never counts as an echo
LOW_INFO_ECHO_TAIL_CHARS = 80   # body text beyond the echoed description shorter than this = nothing
NEAR_DUP_JACCARD = 0.6          # salient-term Jaccard similarity for a near-duplicate pair
NEAR_DUP_MIN_SHARED = 3         # a pair must also share at least this many salient terms
GENERIC_TERM_SHARE = 0.4        # a term in more than this share of notes (and > 2) is corpus-generic
NEVER_PROMOTED_DAYS = 30        # a draft older than this was never promoted
OVERSIZED_TYPE_SHARE = 0.6      # one type above this share of the bundle...
OVERSIZED_TYPE_MIN_NOTES = 20   # ...of a bundle at least this big

# Lines carrying these phrases are filler that an automation filing notes in bulk writes into every
# note (seen in the wild in auto-filed report shards); they never count as information. Matched
# case-insensitively as substrings of one body line. Extend the list when a new filer shows up.
BOILERPLATE_PHRASES = (
    "recorded automatically",       # a "## Why" line that only says the note was filed by a tool
    "accepted (agent-authored",     # a "## Status" line stamped on every note
    "not a human ruling",
    "accepted from contract",       # a hand-off item copied over verbatim
)

# Same order okf_normalize.py uses (OKF v0.2 spec). Only used to place a `status`
# key that a note does not have yet; existing keys are never reordered.
KEY_ORDER = ["type", "title", "description", "resource", "tags",
             "generated", "created", "valid_as_of", "sources", "status",
             "verified", "stale_after", "relations"]
TYPE_ENUM = {"gotcha", "workaround", "schema", "decision", "pattern", "runbook", "reference",
             "open-question"}
RESERVED = {"index.md", "log.md"}
BACKUP_DIR = ".okf-backups"

# Legacy status -> its OKF v0.2 meaning (the spec's status table).
LEGACY_STATUS = {"unverified": "draft", "open": "draft", "verified": "stable",
                 "stale": "deprecated", "closed": "deprecated"}
# Relations that record history, not dependence: a note that supersedes a deprecated one may keep
# pointing at it without that counting as "still linked".
HISTORICAL_RELATIONS = {"supersedes", "duplicates", "contradicts"}

ACTIONS = ("keep", "delete", "deprecate", "merge-into", "promote")
_RANK = {"delete": 5, "merge-into": 4, "deprecate": 3, "promote": 2, "keep": 1}

KINDS = ("BURST", "LOW_INFO", "NEAR_DUP", "STALE", "NEVER_PROMOTED", "ORPHAN", "OVERSIZED_TYPE")
KIND_HELP = {
    "BURST": f">= {BURST_MIN_NOTES} notes of one type citing one source, filed on one day",
    "LOW_INFO": "little beyond boilerplate, a markdown-junk title, or a title/description echo",
    "NEAR_DUP": f"salient-term Jaccard >= {NEAR_DUP_JACCARD}; keep the older, merge the newer",
    "STALE": "stale_after passed, legacy status: stale, or deprecated but still linked",
    "NEVER_PROMOTED": f"draft (legacy unverified/open) for more than {NEVER_PROMOTED_DAYS} days",
    "ORPHAN": "no other note links or relates to it (weak signal)",
    "OVERSIZED_TYPE": f"one type is over {int(OVERSIZED_TYPE_SHARE * 100)}% of the bundle (hint)",
}

_STOP = set((
    "the a an and or of to in on for with is are was were be been this that these those it its by "
    "as at use using used via from into per note notes new old fix when then than only not no yes "
    "you your our we run runs ran md ai memory project notes-about has have had can will would "
    "should could does did how what which who why where all any each every some more most other "
    "such them they their there here also just very about after before over under again once both "
    "same own too out off but if so do"
).split())

_MD_LINK = re.compile(r"\]\(([^)\s]+\.md)(#[^)\s]*)?\)")
_TERM = re.compile(r"[a-z][a-z0-9-]{2,}")
_KEY_LINE = re.compile(r"^([A-Za-z_][\w-]*)\s*:")
_MD_NOISE = re.compile(r"[*`]")
_SEP_ROW = re.compile(r"^\|?[\s:|-]+\|?$")
_CELL_SPLIT = re.compile(r"(?<!\\)\|")
_PLAN_MARK = "<!-- lk-audit-knowledge plan; bundle: {} -->"
_PLAN_MARK_RE = re.compile(r"<!--\s*lk-audit-knowledge plan; bundle:\s*(.+?)\s*-->")
REINDEX_CMD = "ai/scripts/okf --reindex && ai/scripts/okf --check"
REINDEX_HINT = f"now run: {REINDEX_CMD}"


def _safe_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def find_git_root(start: Path) -> Path | None:
    p = start.resolve()
    for cand in [p, *p.parents]:
        if (cand / ".git").exists():
            return cand
    return None


# --------------------------------------------------------------------------- frontmatter (dup)

def _fm_end(lines: list[str]) -> int | None:
    """Index of the closing `---`, None when the first line does not open a frontmatter block,
    -1 when the block is never closed."""
    if not lines or lines[0].lstrip("\ufeff").strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return i
    return -1


def parse_frontmatter(text: str):
    """Return (fm_dict | None, body, error | None). Never raises on dirty input."""
    lines = text.splitlines()
    end = _fm_end(lines)
    if end is None:
        return None, text, "no frontmatter block"
    if end == -1:
        return None, text, "frontmatter block is never closed"
    try:
        fm = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as e:
        first = (str(e).splitlines() or ["error"])[0]
        return None, text, f"frontmatter is not valid YAML ({first})"
    if fm is None:
        fm = {}
    if not isinstance(fm, dict):
        return None, text, "frontmatter is not a key/value mapping"
    return fm, "\n".join(lines[end + 1:]).lstrip("\n"), None


def _as_datetime(v) -> datetime | None:
    """Any date-ish frontmatter value -> an aware UTC datetime, or None."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)
    s = str(v).strip()
    for cand in (s[:-1] + "+00:00" if s.endswith("Z") else s, s[:10]):
        try:
            d = datetime.fromisoformat(cand)
        except ValueError:
            continue
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return None


def _text(v) -> str:
    return "" if v is None else re.sub(r"\s+", " ", str(v)).strip()


def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", _MD_NOISE.sub("", s)).strip()


# --------------------------------------------------------------------------- notes

@dataclass
class Note:
    rel: str                 # bundle-relative POSIX path
    path: Path
    fm: dict
    body: str
    type: str
    title: str
    description: str
    status_raw: str          # as written (lowercased)
    status: str              # its OKF v0.2 meaning ("" when absent)
    filed: date | None       # created, else generated.at / timestamp / updated
    order_key: tuple         # sorts older notes first
    source: str | None       # first source resource, normalised
    terms: frozenset


def _source_key(s) -> str | None:
    """A source string -> the resource it names. Legacy sources carry trailing prose
    ("ai/x.md §2 (Codex r2)"); the leading path token is the resource."""
    s = _text(s)
    if not s:
        return None
    tok = s.split(" ", 1)[0].rstrip(",;")
    if "/" in tok or "\\" in tok or tok.lower().endswith(".md"):
        return tok.replace("\\", "/")
    return s


def _first_source(fm: dict) -> str | None:
    srcs = fm.get("sources")
    first = srcs[0] if isinstance(srcs, list) and srcs else srcs
    if isinstance(first, dict):
        first = first.get("resource")
    if not first:
        legacy = fm.get("source")
        if isinstance(legacy, list):
            legacy = legacy[0] if legacy else None
        first = str(legacy).split(";")[0] if legacy else None
    return _source_key(first) if first else None


def _note_terms(rel: str, fm: dict) -> frozenset:
    """Salient terms: de-typed slug tokens + title + description, lowercased, stop-words out
    (the same recipe as okf_normalize.py --suggest-links, minus tags)."""
    stem = Path(rel).stem
    head, sep, tail = stem.partition("_")
    if sep and head in TYPE_ENUM:
        stem = tail
    text = f"{stem.replace('-', ' ')} {_text(fm.get('title'))} {_text(fm.get('description'))}".lower()
    terms = {w.strip("-") for w in _TERM.findall(text)}
    return frozenset(t for t in terms if len(t) >= 3 and t not in _STOP)


def _make_note(rel: str, path: Path, fm: dict, body: str) -> Note:
    gen = fm.get("generated")
    gen_at = gen.get("at") if isinstance(gen, dict) else None
    when = next((d for d in map(_as_datetime, (gen_at, fm.get("timestamp"), fm.get("updated"))) if d),
                None)
    born = _as_datetime(fm.get("created")) or when
    status_raw = _text(fm.get("status")).lower()
    return Note(
        rel=rel, path=path, fm=fm, body=body,
        type=_text(fm.get("type")), title=_text(fm.get("title")),
        description=_text(fm.get("description")),
        status_raw=status_raw, status=LEGACY_STATUS.get(status_raw, status_raw),
        filed=born.date() if born else None,
        order_key=(born.date().isoformat() if born else "9999", when.isoformat() if when else "~", rel),
        source=_first_source(fm), terms=_note_terms(rel, fm))


def load_bundle(bundle: Path):
    """Return (notes, malformed). Reserved files and .okf-backups are never concepts; a note that
    cannot be read or parsed is skipped and reported, never fatal."""
    notes, malformed = [], []
    for p in sorted(bundle.rglob("*.md")):
        parts = p.relative_to(bundle).parts
        if p.name.lower() in RESERVED or BACKUP_DIR in parts:
            continue
        rel = Path(*parts).as_posix()
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            malformed.append({"path": rel, "reason": "not readable as UTF-8"})
            continue
        fm, body, err = parse_frontmatter(text)
        if err:
            malformed.append({"path": rel, "reason": err})
            continue
        notes.append(_make_note(rel, p, fm, body))
    return notes, malformed


def build_links(bundle: Path, notes: list[Note]):
    """Return (inbound: rel -> [(source_rel, kind)], related: set of frozenset pairs).
    kind is "link" for a markdown link, else the relation verb."""
    by_path = {os.path.normcase(str(n.path.resolve())): n for n in notes}
    inbound: dict[str, list] = defaultdict(list)
    related: set = set()
    for n in notes:
        targets = []
        for m in _MD_LINK.finditer(n.body):
            t = unquote(m.group(1))
            if "://" not in t:
                targets.append((t, "link"))
        rels = n.fm.get("relations")
        for r in ([rels] if isinstance(rels, str) else rels if isinstance(rels, list) else []):
            parts = str(r).strip().split(None, 1)
            if len(parts) == 2:
                targets.append((parts[1].strip().strip("`"), parts[0].rstrip(":").lower()))
        for t, kind in targets:
            base = bundle if t.startswith("/") else n.path.parent
            tgt = by_path.get(os.path.normcase(str((base / t.lstrip("/")).resolve())))
            if tgt is None or tgt is n:
                continue
            inbound[tgt.rel].append((n.rel, kind))
            if kind not in ("link", "duplicates"):
                related.add(frozenset({n.rel, tgt.rel}))
    return inbound, related


# --------------------------------------------------------------------------- heuristics

def _info_text(body: str) -> str:
    """Body text that carries information: minus headings, the Verify line, boilerplate lines."""
    kept = []
    for line in body.splitlines():
        s = line.strip()
        low = s.lower()
        if (not s or s.startswith("#") or low.startswith(("**verify:**", "verify:"))
                or any(ph in low for ph in BOILERPLATE_PHRASES)):
            continue
        kept.append(s)
    return _plain(" ".join(kept))


def low_info_reasons(n: Note) -> list[str]:
    info = _info_text(n.body)
    reasons = []
    if len(info) < LOW_INFO_MIN_CHARS:
        reasons.append(f"body is {len(info)} chars after boilerplate (< {LOW_INFO_MIN_CHARS})")
    if n.title.startswith("**"):
        reasons.append("title starts with `**`")
    elif n.title.startswith("`"):
        reasons.append("title starts with a backtick")
    pt, pd = _plain(n.title).lower(), _plain(n.description).lower()
    k = min(LOW_INFO_PREFIX_CHARS, len(pt))
    if k >= LOW_INFO_ECHO_MIN_CHARS and pt[:k] == pd[:k]:
        novel, low = info, info.lower()
        for echo in (pd.rstrip(" ."), pt.rstrip(" .")):
            if echo and low.startswith(echo):
                novel = info[len(echo):].strip()
                break
        if len(novel) < LOW_INFO_ECHO_TAIL_CHARS:
            reasons.append(f"title is the description's first {k} chars and the body only restates them")
    return reasons


def find_bursts(notes: list[Note]) -> list[tuple[tuple, list[Note]]]:
    groups: dict[tuple, list[Note]] = defaultdict(list)
    for n in notes:
        if n.source and n.filed:
            groups[(n.source, n.filed.isoformat(), n.type)].append(n)
    return [(k, sorted(g, key=lambda n: n.rel))
            for k, g in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0], kv[0][2]))
            if len(g) >= BURST_MIN_NOTES]


def find_near_dups(notes: list[Note], related: set):
    """Pairs (jaccard, older, newer, shared) at or above NEAR_DUP_JACCARD, most similar first.
    Pairs already joined by a typed relation (other than `duplicates`) were judged distinct."""
    df = Counter(t for n in notes for t in n.terms)
    generic = {t for t, c in df.items() if c > max(2, len(notes) * GENERIC_TERM_SHARE)}
    salient = {n.rel: n.terms - generic for n in notes}
    by_term: dict[str, list[Note]] = defaultdict(list)
    for n in notes:
        for t in salient[n.rel]:
            by_term[t].append(n)
    seen, pairs = set(), []
    for members in by_term.values():
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                key = frozenset({a.rel, b.rel})
                if key in seen:
                    continue
                seen.add(key)
                shared = salient[a.rel] & salient[b.rel]
                if key in related or len(shared) < NEAR_DUP_MIN_SHARED:
                    continue
                jac = len(shared) / len(salient[a.rel] | salient[b.rel])
                if jac >= NEAR_DUP_JACCARD:
                    older, newer = sorted((a, b), key=lambda n: n.order_key)
                    pairs.append((jac, older, newer, shared))
    pairs.sort(key=lambda p: (-p[0], p[1].rel, p[2].rel))
    return pairs


def audit(bundle: Path, *, now: datetime | None = None) -> dict:
    """Run every heuristic. Returns a JSON-ready dict: findings, suggested plan rows, summary."""
    now = now or datetime.now(timezone.utc)
    today = now.date()
    notes, malformed = load_bundle(bundle)
    inbound, related = build_links(bundle, notes)
    findings: list[dict] = []
    suggest: dict[str, list[tuple[str, str | None, str]]] = defaultdict(list)

    def add(rel, action, reason, target=None):
        suggest[rel].append((action, target, reason))

    low_info = {n.rel: r for n in notes if (r := low_info_reasons(n))}

    for (src, day, typ), cluster in find_bursts(notes):
        low = sum(1 for n in cluster if n.rel in low_info)
        junk = low / len(cluster) >= BURST_JUNK_SHARE
        what = f"{len(cluster)} `{typ or '?'}` notes filed {day} citing {src}"
        findings.append({"kind": "BURST", "notes": [n.rel for n in cluster],
                         "reason": f"{what} ({low} of them low-info)"})
        for n in cluster:
            if n.rel in low_info:
                add(n.rel, "delete", f"BURST: one of {what}, and low-info")
            elif junk:
                add(n.rel, "delete", f"BURST: one of {what}, {low} of them low-info; "
                                     "delete unless it says something its source does not")
            else:
                add(n.rel, "keep", f"BURST: one of {what}; read it against its source")

    for n in notes:
        if n.rel in low_info:
            reason = "; ".join(low_info[n.rel])
            findings.append({"kind": "LOW_INFO", "notes": [n.rel], "reason": reason})
            add(n.rel, "keep", f"LOW_INFO: {reason}: expand it or delete it")

    deleting = {rel for rel, s in suggest.items() if any(a == "delete" for a, _, _ in s)}
    merge_target: dict[str, str] = {}
    for jac, older, newer, shared in find_near_dups(notes, related):
        terms = ", ".join(sorted(shared)[:6])
        findings.append({"kind": "NEAR_DUP", "notes": [older.rel, newer.rel],
                         "reason": f"jaccard {jac:.2f} on {{{terms}}}; {older.rel} is older"})
        if newer.rel in deleting or older.rel in deleting:
            add(newer.rel, "keep", f"NEAR_DUP: {jac:.2f} with {older.rel}")
            add(older.rel, "keep", f"NEAR_DUP: {jac:.2f} with {newer.rel}")
        elif newer.rel not in merge_target:
            merge_target[newer.rel] = older.rel
            add(newer.rel, "merge-into", f"NEAR_DUP: {jac:.2f} with the older {older.rel}; "
                                         "fold anything new into it", target=older.rel)
            add(older.rel, "keep", f"NEAR_DUP: older of a pair with {newer.rel}; keep it")
        else:
            add(newer.rel, "keep", f"NEAR_DUP: also {jac:.2f} with {older.rel}")

    for n in notes:
        reasons, action = [], None
        sa = _as_datetime(n.fm.get("stale_after"))
        if sa and sa < now and n.status != "deprecated":
            reasons.append(f"stale_after {sa.date()} has passed: re-verify and re-promote, or deprecate")
            action = "deprecate"
        if n.status_raw == "stale":
            reasons.append("legacy status: stale")
            action = "deprecate"
        if n.status == "deprecated":
            historical = {s for s, kind in inbound.get(n.rel, []) if kind in HISTORICAL_RELATIONS}
            live = sorted({s for s, _ in inbound.get(n.rel, []) if s not in historical})
            if live:
                reasons.append(f"status {n.status_raw} but still linked from {', '.join(live)}: "
                               "repoint or drop those links")
                action = action or "keep"
        if reasons:
            reason = "; ".join(reasons)
            findings.append({"kind": "STALE", "notes": [n.rel], "reason": reason})
            add(n.rel, action, f"STALE: {reason}")

    for n in notes:
        if n.status == "draft" and n.filed and (today - n.filed).days > NEVER_PROMOTED_DAYS:
            days = (today - n.filed).days
            if n.type == "open-question":
                # Promoting a question settles nothing: the answer is a decision note that
                # `supersedes` it, which also keeps the deprecated question out of STALE.
                reason = f"open question still a draft after {days} days (status: {n.status_raw})"
                add(n.rel, "keep", f"NEVER_PROMOTED: {reason}: undecided fork: answer it with a "
                                   "decision note that supersedes it, then deprecate this one")
            else:
                reason = f"draft for {days} days (status: {n.status_raw})"
                add(n.rel, "promote", f"NEVER_PROMOTED: {reason}: check it, then promote or delete")
            findings.append({"kind": "NEVER_PROMOTED", "notes": [n.rel], "reason": reason})

    for n in notes:
        if not inbound.get(n.rel):
            findings.append({"kind": "ORPHAN", "notes": [n.rel],
                             "reason": "no inbound link or relation from another note"})
            add(n.rel, "keep", "ORPHAN: nothing links here")

    types = Counter(n.type or "?" for n in notes)
    if len(notes) >= OVERSIZED_TYPE_MIN_NOTES and types:
        typ, count = types.most_common(1)[0]
        if count / len(notes) > OVERSIZED_TYPE_SHARE:
            findings.append({"kind": "OVERSIZED_TYPE", "notes": [],
                             "reason": f"`{typ}` is {count} of {len(notes)} notes "
                                       f"({count * 100 // len(notes)}%)"})

    plan = []
    for rel, sugg in suggest.items():
        action, target, _ = max(sugg, key=lambda s: _RANK[s[0]])
        plan.append({"action": f"merge-into:{target}" if target else action, "path": rel,
                     "reason": "; ".join(dict.fromkeys(r for _, _, r in sugg)),
                     "weak": all(r.startswith("ORPHAN") for _, _, r in sugg)})
    plan.sort(key=lambda r: (r["weak"], -_RANK[r["action"].split(":", 1)[0]], r["path"]))

    count = Counter(f["kind"] for f in findings)
    summary = {k: count.get(k, 0) for k in KINDS}
    summary["BURST_notes"] = sum(len(f["notes"]) for f in findings if f["kind"] == "BURST")
    summary["MALFORMED"] = len(malformed)
    summary["suggested"] = dict(Counter(r["action"].split(":", 1)[0] for r in plan))
    return {"tool": "lk-audit-knowledge", "version": TOOL_VERSION, "bundle": str(bundle),
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "notes": len(notes),
            "findings": findings, "malformed": malformed, "plan": plan, "summary": summary}


# --------------------------------------------------------------------------- report / plan

def summary_line(r: dict) -> str:
    s = r["summary"]
    sugg = s["suggested"]
    return (f"summary: {r['notes']} notes | BURST {s['BURST']} ({s['BURST_notes']} notes) | "
            f"LOW_INFO {s['LOW_INFO']} | NEAR_DUP {s['NEAR_DUP']} | STALE {s['STALE']} | "
            f"NEVER_PROMOTED {s['NEVER_PROMOTED']} | ORPHAN {s['ORPHAN']} | "
            f"OVERSIZED_TYPE {s['OVERSIZED_TYPE']} | MALFORMED {s['MALFORMED']} | suggested: "
            + ", ".join(f"{a} {sugg.get(a, 0)}" for a in ("delete", "merge-into", "deprecate", "promote")))


def render_report(r: dict) -> str:
    out = [f"lk-audit-knowledge {TOOL_VERSION} -- {r['bundle']} ({r['notes']} notes)", ""]
    for kind in KINDS:
        fs = [f for f in r["findings"] if f["kind"] == kind]
        out.append(f"{kind} ({len(fs)}) -- {KIND_HELP[kind]}")
        for f in fs:
            if kind == "NEAR_DUP":
                out.append(f"  {f['notes'][0]} <-> {f['notes'][1]} -- {f['reason']}")
            elif len(f["notes"]) == 1:
                out.append(f"  {f['notes'][0]} -- {f['reason']}")
            else:
                out.append(f"  {f['reason']}")
                out.extend(f"    {n}" for n in f["notes"])
        out.append("")
    if r["malformed"]:
        out.append(f"MALFORMED ({len(r['malformed'])}) -- skipped; fix with okf --check")
        out.extend(f"  {m['path']} -- {m['reason']}" for m in r["malformed"])
        out.append("")
    out.append(summary_line(r))
    return "\n".join(out) + "\n"


def _cell(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def render_plan(r: dict, bundle: Path) -> str:
    def table(rows):
        if not rows:
            return ["(none)"]
        return (["| action | path | reason |", "|---|---|---|"]
                + [f"| {_cell(x['action'])} | {_cell(x['path'])} | {_cell(x['reason'])} |" for x in rows])

    main = [x for x in r["plan"] if not x["weak"]]
    weak = [x for x in r["plan"] if x["weak"]]
    hints = [f"- {f['kind']}: {f['reason']}" for f in r["findings"] if f["kind"] == "OVERSIZED_TYPE"]
    hints += [f"- MALFORMED {m['path']}: {m['reason']} (skipped; fix with okf --check)"
              for m in r["malformed"]]
    lines = [
        _PLAN_MARK.format(bundle.resolve()),
        f"# Knowledge audit plan: {r['bundle']}",
        "",
        f"Written {r['generated_at']} by lk-audit-knowledge {TOOL_VERSION} from {r['notes']} notes.",
        "",
        "Every action below is a heuristic SUGGESTION, not a verdict. Before anything is applied:",
        "",
        "1. The agent opens every flagged note (and, for a burst, the source it cites), decides, and",
        "   edits the action column. Change a row to `keep`, or delete the row, to leave a note alone.",
        "2. A human reads the edited plan and approves it.",
        f"3. `audit_knowledge.py {r['bundle']} --apply <this file>`, then `{REINDEX_CMD}`.",
        "",
        "Actions: `keep`, `delete`, `deprecate`, `merge-into:<path>`, `promote`. Paths are relative to",
        "the bundle. Only table rows are read; everything else in this file is commentary.",
        "",
        f"## Suggested actions ({len(main)})",
        "",
        *table(main),
        "",
        f"## Weak signals: orphans only ({len(weak)}; keep unless you know better)",
        "",
        *table(weak),
        "",
        "## Bundle hints (not actions)",
        "",
        *(hints or ["(none)"]),
        "",
        summary_line(r),
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- apply

@dataclass
class PlanRow:
    line: int
    action: str
    path: str
    target: str | None
    reason: str


def parse_plan(text: str):
    """Return (rows, errors). Only markdown table rows (lines starting with `|`) are read."""
    rows, errors = [], []
    for i, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if not s.startswith("|") or _SEP_ROW.match(s):
            continue
        cells = [c.strip().replace("\\|", "|") for c in _CELL_SPLIT.split(s)[1:]]
        if cells and cells[-1] == "":
            cells.pop()
        if len(cells) < 2:
            errors.append(f"line {i}: a row needs `| action | path | reason |`")
            continue
        verb, _, target = cells[0].strip("`").strip().partition(":")
        verb = verb.strip().lower()
        if verb == "action":
            continue                                    # the header row
        path = cells[1].strip().strip("`").strip()
        target = target.strip().strip("`").strip() or None
        if verb not in ACTIONS:
            errors.append(f"line {i}: unknown action {cells[0]!r} (use one of: {', '.join(ACTIONS)})")
        elif verb == "merge-into" and not target:
            errors.append(f"line {i}: merge-into needs a target: `merge-into:<path>`")
        elif verb != "merge-into" and target:
            errors.append(f"line {i}: only merge-into takes a `:<path>` target")
        elif not path:
            errors.append(f"line {i}: empty path")
        else:
            rows.append(PlanRow(i, verb, path, target, " | ".join(cells[2:]).strip()))
    return rows, errors


def _member(bundle_res: Path, p: str):
    """Resolve a plan path to a concept file inside the bundle: (path, None) or (None, why)."""
    cand = Path(p.replace("\\", "/"))
    full = (cand if cand.is_absolute() else bundle_res / cand).resolve()
    if full == bundle_res or not full.is_relative_to(bundle_res):
        return None, "is outside the bundle"
    if full.name.lower() in RESERVED:
        return None, "is a reserved file (index.md / log.md), not a concept"
    if BACKUP_DIR in full.relative_to(bundle_res).parts:
        return None, f"is inside {BACKUP_DIR}"
    if full.suffix.lower() != ".md":
        return None, "is not a .md concept"
    return full, None


def set_status_deprecated(path: Path):
    """Set `status: deprecated` by editing that one frontmatter line in place: every other key, its
    order, quoting and comments, the body, and the file's line endings stay byte-for-byte.
    Returns (previous_status | "", error | None)."""
    try:
        raw = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return "", f"cannot read: {e}"
    before, _, err = parse_frontmatter(raw)
    if err:
        return "", err
    lines = raw.splitlines(keepends=True)
    end = _fm_end([ln.rstrip("\r\n") for ln in lines])
    nl = lines[0][len(lines[0].rstrip("\r\n")):] or "\n"
    keys = [(i, m.group(1)) for i in range(1, end) if (m := _KEY_LINE.match(lines[i]))]
    status_at = next((i for i, k in keys if k == "status"), None)
    if status_at is not None:
        j = status_at + 1
        while j < end and lines[j][:1] in (" ", "\t"):    # a folded/continued value
            j += 1
        lines[status_at:j] = [f"status: deprecated{nl}"]
    else:
        later = set(KEY_ORDER[KEY_ORDER.index("status") + 1:])
        at = next((i for i, k in keys if k in later), end)
        lines.insert(at, f"status: deprecated{nl}")
    new = "".join(lines)
    after, _, err = parse_frontmatter(new)
    if err or after.get("status") != "deprecated" or \
            {k: v for k, v in after.items() if k != "status"} != {k: v for k, v in before.items() if k != "status"}:
        return "", "could not set status without disturbing other keys; edit it by hand"
    path.write_bytes(new.encode("utf-8"))
    return _text(before.get("status")), None


def _delete(full: Path, bundle_res: Path, git_root: Path | None, backup: Path) -> str:
    """git rm inside a repo; otherwise (or if git refuses) move to the backup dir. Returns how."""
    why = ""
    if git_root is not None:
        rel = full.relative_to(git_root.resolve()).as_posix()
        r = subprocess.run(["git", "-C", str(git_root), "rm", "-q", "--", rel],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return "git rm"
        why = f"git rm refused: {(r.stderr.strip().splitlines() or ['?'])[0]}; "
    dest = backup / full.relative_to(bundle_res)
    dest.parent.mkdir(parents=True, exist_ok=True)
    n = 2
    while dest.exists():
        dest = dest.with_name(f"{full.stem}-{n}{full.suffix}")
        n += 1
    shutil.move(str(full), str(dest))
    return f"{why}moved to {dest}"


def apply_plan(bundle: Path, plan_path: Path, *, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    bundle_res = bundle.resolve()
    try:
        text = plan_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"REFUSED: cannot read plan {plan_path}: {e}")
        return 2
    rows, errors = parse_plan(text)
    mark = _PLAN_MARK_RE.search(text)
    if mark and os.path.normcase(mark.group(1)) != os.path.normcase(str(bundle_res)):
        errors.insert(0, f"the plan was written for bundle {mark.group(1)}, not {bundle_res}: "
                         "regenerate it with --plan (or fix its first line if the bundle moved)")
    resolved = []
    for row in rows:
        full, why = _member(bundle_res, row.path)
        if why:
            errors.append(f"line {row.line}: {row.action} {row.path}: path {why}")
            continue
        target = None
        if row.target:
            target, why = _member(bundle_res, row.target)
            if why:
                errors.append(f"line {row.line}: merge-into target {row.target} {why}")
                continue
            if target == full:
                errors.append(f"line {row.line}: {row.path} cannot merge into itself")
                continue
        resolved.append((row, full, target))
    if errors:
        print(f"REFUSED: {len(errors)} problem(s) in {plan_path}; nothing was applied.")
        for e in errors:
            print(f"  {e}")
        return 2

    git_root = find_git_root(bundle_res)
    backup = bundle_res.parent / BACKUP_DIR / f"audit-{now.date().isoformat()}"
    deleting = {full for row, full, _ in resolved if row.action == "delete"}
    done, failures, promote = Counter(), 0, []
    for row, full, target in resolved:
        rel = full.relative_to(bundle_res).as_posix()
        if row.action == "keep":
            done["keep"] += 1
        elif row.action == "delete":
            if not full.exists():
                print(f"  delete      {rel}: already gone")
                continue
            print(f"  delete      {rel} ({_delete(full, bundle_res, git_root, backup)})")
            done["delete"] += 1
        elif row.action == "deprecate":
            if not full.exists():
                print(f"  deprecate   {rel}: FAILED, no such file")
                failures += 1
                continue
            was, err = set_status_deprecated(full)
            if err:
                print(f"  deprecate   {rel}: FAILED, {err}")
                failures += 1
            else:
                print(f"  deprecate   {rel} (status: {was or 'absent'} -> deprecated)")
                done["deprecate"] += 1
        elif row.action == "promote":
            shown = full.relative_to(git_root.resolve()).as_posix() if git_root else str(full)
            promote.append(shown)
            print(f"  promote     {rel}: not done here (promotion is a human verb)")
        else:  # merge-into
            trel = target.relative_to(bundle_res).as_posix()
            warn = "  WARNING: the target is also marked delete in this plan" if target in deleting else ""
            print(f"  merge-into  {rel} -> {trel}: merge by hand (fold what is new into {trel}, "
                  f"then delete {rel}){warn}")
            done["merge-into (by hand)"] += 1
    print("applied: " + (", ".join(f"{k} {v}" for k, v in done.items()) or "nothing")
          + (f"; {failures} FAILED" if failures else ""))
    if promote:
        print(f"promote with: ai/scripts/okf --promote {' '.join(promote)}")
    print(REINDEX_HINT)
    return 1 if failures else 0


# --------------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    _safe_stdio()
    ap = argparse.ArgumentParser(
        prog="audit_knowledge.py",
        description="Find surplus, duplicate, stale and low-information notes in an OKF bundle. "
                    "Heuristics only: an agent judges each finding and a human approves the plan.")
    ap.add_argument("bundle", nargs="?", default=DEFAULT_BUNDLE, type=Path,
                    help=f"bundle dir (default: {DEFAULT_BUNDLE})")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="print findings and suggested rows as JSON")
    mode.add_argument("--plan", type=Path, metavar="OUT.md", help="write an editable triage plan")
    mode.add_argument("--apply", type=Path, metavar="PLAN.md",
                      help="execute an approved plan (delete, deprecate; prints merge/promote)")
    ap.add_argument("--version", action="version", version=f"lk-audit-knowledge {TOOL_VERSION}")
    args = ap.parse_args(argv)

    bundle: Path = args.bundle
    if not bundle.is_dir():
        print(f"no such bundle directory: {bundle} (pass the path to ai/memory)")
        return 2
    if args.apply:
        return apply_plan(bundle, args.apply)
    r = audit(bundle)
    if args.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
    elif args.plan:
        out: Path = args.plan
        if out.resolve().is_relative_to(bundle.resolve()):
            print(f"REFUSED: {out} is inside the bundle, where it would be read as a note. "
                  "Write the plan somewhere else (e.g. ai/scratch/ or a temp dir).")
            return 2
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_plan(r, bundle), encoding="utf-8")
        print(f"wrote {out}: {len([x for x in r['plan'] if not x['weak']])} suggested action(s), "
              f"{len([x for x in r['plan'] if x['weak']])} weak signal(s). "
              "An agent edits it, a human approves it, then --apply it.")
        print(summary_line(r))
    else:
        sys.stdout.write(render_report(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
