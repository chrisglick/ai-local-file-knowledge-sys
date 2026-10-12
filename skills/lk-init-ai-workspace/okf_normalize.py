#!/usr/bin/env python3
"""Normalize / check / maintain an ai/memory/ knowledge bundle toward literal OKF v0.2.

OKF = Open Knowledge Format (GoogleCloudPlatform/open-knowledge-format, formerly knowledge-catalog/okf):
a directory of markdown files with YAML frontmatter. This enforces OKF naming/structure as the
stable standard so agents stop inventing per-session variants, while PRESERVING our anti-rot
extensions (`created` / `relations` / the body's **Verify:** line) which OKF tolerates as unknown keys.

Since 0.9 the tool speaks the spec's own vocabulary and MIGRATES the legacy one on --apply:
  timestamp            -> generated: {by, at}            (spec: who produced it, last meaningful change)
  source: "a; b"       -> sources: [{resource: a}, ...]  (spec: provenance list)
  status: unverified   -> status: draft                  (spec enum is draft | stable | deprecated)
  status: verified     -> status: stable
  status: stale        -> status: deprecated
  verified_on: DATE    -> verified: [{by: human:<id>, at}] + stale_after: DATE + 90d

Verbs (default is a read-only dry-run report):
  okf_normalize.py BUNDLE                 dry-run report (frontmatter drift + migrations + renames + hints)
  okf_normalize.py BUNDLE --check         strict report; exit 1 on ANY drift/error/warning (for hooks/CI)
  okf_normalize.py BUNDLE --apply         rewrite frontmatter in place (auto-backup when not in git)
  okf_normalize.py BUNDLE --reindex       regenerate root + nested index.md from frontmatter
  okf_normalize.py BUNDLE --move SRC DST  move a note and rewrite every inbound link
  okf_normalize.py BUNDLE --touch PATH... bump a note's generated.at (last-meaningful-change) to today
  okf_normalize.py BUNDLE --review        list status: draft concepts (the promotion queue)
  okf_normalize.py BUNDLE --promote PATH... [--actor human:<id>]
                                          human promotion: status stable + a verified entry + stale_after
  okf_normalize.py BUNDLE --suggest-links surface note pairs that share terms but aren't linked (a hint)
  okf_normalize.py --version              print tool + standard version

Actor resolution (for generated.by on migrated notes, and for --promote / --touch): --actor, else the
`actor = human:<id>` key in ai/okf.conf, else `human:<git config user.name>`, else `human:unknown`.

Deps: pyyaml only. Self-defends stdout to UTF-8 (Windows-console safe), tolerates dirty input
(non-UTF-8 files, BOMs, malformed YAML) by reporting + skipping rather than crashing.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

# Versions — stamped so projects can detect when their copy/standard is behind.
TOOL_VERSION = "0.9"  # 0.9: OKF v0.2 vocabulary (generated/sources/verified/stale_after, spec status
                      # enum) with legacy migration on --apply; --promote; root index okf_version.
# 0.8: conversation provenance -- prose/unresolvable `source:` warns. 0.7: --suggest-links.
# 0.6: agent-memory-research adoptions (`workaround` type, typed `relations`, 90-day decay).
# 0.5: --review promotion queue. 0.4: dirty-input + cross-platform hardening. 0.3: malformed-YAML survival.
OKF_STANDARD_VERSION = "0.2"
LK_VERSION = "1.0.0"  # the lk skill-set release this engine ships in (lk-doctor compares it)

# OKF reserved files (no frontmatter; skipped as concepts).
RESERVED = {"index.md", "log.md"}

# Our type enum (valid OKF type strings; also the filename prefix convention).
# `workaround` (cq lifecycle.kind) = a TEMPORARY fix expected to be superseded once tooling exists;
# distinct from a `gotcha`, which is a permanent external constraint.
# `open-question` = a fork nobody has decided yet; closed by writing a `decision` note that
# `supersedes` it and marking the question `deprecated` with a `relates` back-link.
# `correction` (lk-end-session) = a human-caught wrong claim: **Wrong:** / **Right:** / **Why tempting:**.
TYPE_ENUM = {"gotcha", "workaround", "schema", "decision", "pattern", "runbook", "reference",
             "open-question", "correction"}

# Ordered (type -> index heading) for grouping concepts within a directory index.
TYPE_HEADINGS = [
    ("gotcha", "Gotchas"),
    ("correction", "Corrections (claims a human caught as wrong)"),
    ("workaround", "Workarounds (temporary — expect supersession)"),
    ("schema", "Schema / Constants"),
    ("decision", "Decisions"),
    ("open-question", "Open questions (undecided forks — close with a decision note)"),
    ("pattern", "Patterns"),
    ("runbook", "Runbooks"),
    ("reference", "Reference (external pointers)"),
]

# Typed relations between concepts (beads/cq prior art): a small, queryable vocabulary so the
# graph carries meaning, not just undifferentiated edges. Frontmatter `relations:` is a list of
# "<verb> <relative-path>" strings, validated by --check (verb known + target resolves).
RELATION_VERBS = {"supersedes", "extends", "refines", "contradicts", "relates", "duplicates"}

# OKF v0.2 lifecycle enum. Absent means stable. Our semantics layered on it:
#   draft      = machine/agent-authored, not yet human-checked (the promotion queue)
#   stable     = human-checked (carries a `verified` entry with a human: actor)
#   deprecated = known wrong / superseded (re-verify or delete)
STATUS_ENUM = {"draft", "stable", "deprecated"}
LEGACY_STATUS_MAP = {"unverified": "draft", "verified": "stable", "stale": "deprecated",
                     "open": "draft", "closed": "deprecated"}
# Legacy keys that --apply migrates (their presence is mechanical drift).
LEGACY_KEYS = ("updated", "timestamp", "source", "verified_on")

# A verified note is stale this many days after its last verification (cq confirm-or-decay anti-rot).
# --promote writes it as an explicit spec `stale_after`; --check also derives it when absent.
STALE_AFTER_DAYS = 90

# Actor shapes the spec names: human:<id>, process:<id>, <producer>/<version>.
_ACTOR_RX = re.compile(r"^(human:\S+|process:\S+|[^\s/:]+/\S+)$")
DEFAULT_ACTOR = "human:unknown"

# Everything below this marker in an index.md is regenerated by --reindex; everything
# above it (title, scan-first note, two-stores explainer, etc.) is preserved.
AUTO_SENTINEL = "<!-- okf-index:auto (regenerated by okf_normalize.py --reindex) -->"
# The bundle-root index.md may declare the spec version it targets (spec v0.2).
OKF_VERSION_HEADER = f'---\nokf_version: "{OKF_STANDARD_VERSION}"\n---'

# A flat bundle at/above this many concepts is worth foldering by topic.
FLAT_THRESHOLD = 20

# Canonical frontmatter key order: OKF-recommended first, then provenance/trust, then our extensions.
# Any other tool that writes notes should use this same order so --apply has nothing to rewrite.
KEY_ORDER = ["type", "title", "description", "resource", "tags",
             "generated", "created", "valid_as_of", "sources", "status",
             "verified", "stale_after", "relations"]

_FM_DELIM = "---"
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# index line:  - [Title](file.md) - hook   (em dash or hyphen separator)
_INDEX_LINE = re.compile(r"\[[^\]]*\]\(([^)]+\.md)\)\s*[—\-]\s*(.+?)\s*$")
# markdown link to a .md file (optional #anchor): captures the path
_MD_LINK = re.compile(r"\]\(([^)\s]+\.md)(#[^)\s]*)?\)")
# a file:line or bare path token inside a source resource
_SOURCE_PATH = re.compile(r"([\w./\\-]+\.[A-Za-z0-9]{1,6})(?::\d+)?")


def today_iso() -> str:
    return date.today().isoformat()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_iso_dt(v) -> str:
    """Coerce a YAML date/datetime/str to an ISO 8601 datetime string with a Z designator."""
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.strftime("%Y-%m-%dT%H:%M:%SZ")
        return v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(v, date):
        return f"{v.isoformat()}T00:00:00Z"
    s = str(v).strip()
    if _DATE_ONLY.match(s):
        return f"{s}T00:00:00Z"
    return s


def _iso_date(v):
    """Best-effort date from an ISO datetime/date value; None if unparseable."""
    try:
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        return date.fromisoformat(str(v).strip()[:10])
    except ValueError:
        return None


def _plus_days(iso_dt: str, days: int) -> str:
    d = _iso_date(iso_dt) or date.today()
    return f"{(d + timedelta(days=days)).isoformat()}T00:00:00Z"


def _read_text(path: Path):
    """Read UTF-8; return None (not crash) if the file isn't valid UTF-8 (dirty input)."""
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


_BOM = "﻿"


def _safe_stdio():
    """Make our own output UTF-8 regardless of the console codepage (Windows cp1252 crashes
    when printing a description with an em-dash). No-op if reconfigure is unavailable."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # py3.7+
        except (AttributeError, ValueError):
            pass


# --------------------------------------------------------------------------- actor / conf

def read_conf(bundle: Path) -> dict[str, str]:
    """Parse ai/okf.conf (`key = value` lines, `#` comments) found at bundle/../okf.conf or by
    walking up looking for ai/okf.conf. Empty dict if none."""
    cands = [bundle.parent / "okf.conf"]
    for p in [bundle.resolve(), *bundle.resolve().parents]:
        cands.append(p / "ai" / "okf.conf")
    for c in cands:
        if c.is_file():
            out: dict[str, str] = {}
            for line in (_read_text(c) or "").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
            return out
    return {}


def _git_user_name(cwd: Path):
    try:
        r = subprocess.run(["git", "config", "user.name"], cwd=str(cwd), capture_output=True,
                           text=True, timeout=5)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def resolve_actor(bundle: Path, override: str | None = None) -> str:
    """--actor > ai/okf.conf `actor` > human:<git user.name> > human:unknown."""
    if override and override.strip():
        return override.strip()
    conf_actor = read_conf(bundle).get("actor", "").strip()
    if conf_actor:
        return conf_actor
    name = _git_user_name(bundle if bundle.is_dir() else Path.cwd())
    if name:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if slug:
            return f"human:{slug}"
    return DEFAULT_ACTOR


# --------------------------------------------------------------------------- frontmatter

def parse_frontmatter(text: str):
    """Return (frontmatter_dict_or_None, body_str). None => no frontmatter block."""
    if text.startswith(_BOM):           # strip a UTF-8 BOM (Windows editors) so --- is seen
        text = text[len(_BOM):]
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
        # Malformed frontmatter (e.g. an unquoted value containing ': ') -- never crash the run;
        # treat as unparseable so the caller reports it and skips, like a no-frontmatter file.
        return None, text
    if not isinstance(fm, dict):
        return None, text
    body = "\n".join(lines[end + 1:])
    if body.startswith("\n"):
        body = body[1:]
    return fm, body


def serialize(fm: dict, body: str) -> str:
    ordered = {k: fm[k] for k in KEY_ORDER if k in fm}
    for k in fm:  # preserve any other producer keys, after the known ones
        if k not in ordered:
            ordered[k] = fm[k]
    fm_text = yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True).rstrip()
    if not body.endswith("\n"):
        body += "\n"
    return f"{_FM_DELIM}\n{fm_text}\n{_FM_DELIM}\n\n{body}"


def load_index_descriptions(bundle: Path) -> dict[str, str]:
    """Map concept filename -> curated one-line hook from index/INDEX.md (non-invented)."""
    out: dict[str, str] = {}
    for name in ("index.md", "INDEX.md"):
        p = bundle / name
        if p.exists():
            for line in (_read_text(p) or "").splitlines():
                m = _INDEX_LINE.search(line)
                if m:
                    out[Path(m.group(1)).name] = m.group(2).strip()
            break
    return out


def _as_list(v) -> list:
    if v is None or v == "":
        return []
    return list(v) if isinstance(v, list) else [v]


def sources_list(fm: dict) -> list[dict]:
    """The note's provenance as a list of {resource,...} dicts, reading BOTH the v0.2 `sources`
    and (for not-yet-migrated notes) the legacy `source` string. Read-only helper."""
    out: list[dict] = []
    for s in _as_list(fm.get("sources")):
        if isinstance(s, dict):
            out.append(s)
        elif str(s).strip():
            out.append({"resource": str(s).strip()})
    legacy = fm.get("source")
    if not out and legacy is not None and str(legacy).strip():
        out = [{"resource": p.strip()} for p in str(legacy).split(";") if p.strip()]
    return out


def verified_list(fm: dict) -> list[dict]:
    """`verified` as a list (spec: a bare mapping is a one-element list). Read-only helper."""
    v = fm.get("verified")
    if isinstance(v, dict):
        return [v]
    return [x for x in _as_list(v) if isinstance(x, dict)]


def normalize_fm(fm: dict, descriptions: dict[str, str], filename: str, *, today: str,
                 actor: str = DEFAULT_ACTOR):
    """Return (new_fm, changes:list[str], errors:list[str]) for one concept's frontmatter.

    Migrates the legacy vocabulary to OKF v0.2 (every migration is a reported change).
    tags are OPTIONAL (no longer auto-stubbed) — an always-empty field is cruft.
    """
    fm = dict(fm)
    changes, errors = [], []

    # type (OKF's one hard rule) — cannot synthesize meaning; report if missing.
    t = str(fm.get("type") or "").strip()
    if not t:
        errors.append("missing `type` (OKF requires a non-empty type)")
    elif t not in TYPE_ENUM:
        changes.append(f"note: type '{t}' is outside our enum {sorted(TYPE_ENUM)} (allowed by OKF)")

    # title — fallback to a de-slugged filename so it's never blank.
    if not str(fm.get("title") or "").strip():
        slug = re.sub(r"^(?:%s)_" % "|".join(TYPE_ENUM), "", Path(filename).stem)
        fm["title"] = slug.replace("-", " ").strip().capitalize()
        changes.append(f"add title (derived from filename): {fm['title']!r}")

    # updated / timestamp (legacy) -> generated: {by, at}  (spec: last meaningful change + producer)
    legacy_ts = None
    if "updated" in fm:
        legacy_ts = fm.pop("updated")
        changes.append("drop legacy `updated`")
    gen = fm.get("generated")
    gen = dict(gen) if isinstance(gen, dict) else ({} if gen in (None, "") else {"at": gen})
    if "timestamp" in fm:
        legacy_ts = fm.pop("timestamp")   # timestamp wins over the older `updated`
        changes.append("drop legacy `timestamp` (`generated.at` is canonical)"
                       if str(gen.get("at") or "").strip() else "migrate `timestamp` -> `generated.at`")
    if legacy_ts not in (None, "") and not str(gen.get("at") or "").strip():
        gen["at"] = _to_iso_dt(legacy_ts)
    if gen.get("at") is not None:
        at = _to_iso_dt(gen["at"])
        if at != gen["at"]:
            gen["at"] = at
            changes.append("generated.at -> full ISO 8601 datetime")
    if gen and not str(gen.get("by") or "").strip():
        gen["by"] = actor
        changes.append(f"add generated.by (spec requires it): {actor}")
    if gen:
        ordered = {"by": gen["by"]}
        if gen.get("at") is not None:
            ordered["at"] = gen["at"]
        ordered.update({k: v for k, v in gen.items() if k not in ("by", "at")})
        fm["generated"] = ordered

    # created (set-once) — best-effort backfill from generated.at, else today.
    if not str(fm.get("created") or "").strip():
        at = str((fm.get("generated") or {}).get("at") or "").strip()
        fm["created"] = (at.split("T")[0] if at else today)
        changes.append(f"add created (set-once): {fm['created']}")

    # description — derive from the curated index hook; never invent prose.
    if not str(fm.get("description") or "").strip():
        desc = descriptions.get(filename)
        if desc:
            fm["description"] = desc
            changes.append("add description (from index hook)")
        else:
            errors.append("missing `description` and no index hook to derive it -- write one")

    # tags — optional. Only coerce a present non-list value; never auto-stub [].
    if "tags" in fm and fm.get("tags") not in (None, "") and not isinstance(fm["tags"], list):
        fm["tags"] = [str(fm["tags"])]
        changes.append("coerce tags to a list")

    # source (legacy string) -> sources: [{resource}]  (spec provenance list)
    if "source" in fm:
        legacy_src = fm.pop("source")
        if fm.get("sources"):
            changes.append("drop legacy `source` (`sources` is canonical)")
        else:
            parts = [p.strip() for p in str(legacy_src or "").split(";") if p.strip()]
            if parts:
                fm["sources"] = [{"resource": p} for p in parts]
                changes.append(f"migrate `source` -> `sources` ({len(parts)} resource(s))")
            else:
                changes.append("drop empty legacy `source`")
    if "sources" in fm:
        raw = fm["sources"]
        coerced = []
        for s in (raw if isinstance(raw, list) else [raw]):
            if isinstance(s, dict):
                if not str(s.get("resource") or "").strip():
                    errors.append("a `sources` entry is missing `resource` (spec requires it)")
                coerced.append(s)
            elif s not in (None, ""):
                coerced.append({"resource": str(s).strip()})
        if coerced != raw:
            changes.append("coerce `sources` entries to {resource: ...} mappings")
        fm["sources"] = coerced

    # status — spec enum only; map the legacy vocabulary.
    st_raw = fm.get("status")
    st = str(st_raw or "").strip().lower()
    if st in LEGACY_STATUS_MAP:
        fm["status"] = LEGACY_STATUS_MAP[st]
        changes.append(f"migrate status `{st}` -> `{fm['status']}`")
    elif st and st not in STATUS_ENUM:
        errors.append(f"status '{st}' is not in the OKF enum {sorted(STATUS_ENUM)}")
    elif st_raw is not None and not st:
        fm.pop("status")
        changes.append("drop empty `status` (absent means stable)")

    # verified_on (legacy date) -> verified: [{by, at}] + stale_after  (spec trust + lifecycle)
    if "verified_on" in fm:
        vo = fm.pop("verified_on")
        if vo not in (None, ""):
            at = _to_iso_dt(vo)
            entries = verified_list(fm)
            if not any(str(e.get("at") or "") == at for e in entries):
                entries.append({"by": actor, "at": at})
            fm["verified"] = entries
            changes.append(f"migrate `verified_on` -> `verified` entry ({actor} @ {at})")
            if not fm.get("stale_after"):
                fm["stale_after"] = _plus_days(at, STALE_AFTER_DAYS)
                changes.append(f"add stale_after: {fm['stale_after']}")
        else:
            changes.append("drop empty legacy `verified_on`")
    if "verified" in fm:
        v = fm["verified"]
        if isinstance(v, dict):
            fm["verified"] = [v]
            changes.append("coerce bare `verified` mapping to a one-element list")
        elif not isinstance(v, list):
            errors.append("`verified` must be a list of {by, at} mappings")
    if "stale_after" in fm and fm["stale_after"] not in (None, ""):
        sa = _to_iso_dt(fm["stale_after"])
        if sa != fm["stale_after"]:
            fm["stale_after"] = sa
            changes.append("stale_after -> full ISO 8601 datetime")

    return fm, changes, errors


# ---------------------------------------------------------------------- provenance / links

def check_provenance(fm: dict, body: str, path: Path, repo_root: Path, *, today: str):
    """Anti-rot warnings (our differentiator): missing sources/Verify, dead source path, staleness,
    trust-shape problems. Reads legacy keys too so a mid-migration bundle still gets checked."""
    warns: list[str] = []
    srcs = sources_list(fm)
    if not srcs:
        warns.append("missing `sources` (provenance is mandatory)")
    if "**Verify:**" not in body and "**Verify**" not in body:
        warns.append("missing `**Verify:**` line (the re-check that fights rot)")
    for s in srcs:
        res = str(s.get("resource") or "")
        # A conversation-sourced note (the "why" of a decision lives in chat, not in code) must cite
        # something that still resolves. Prose like "session 2026-06-19" names a source nobody can
        # open, so the claim rots silently -- the exact failure this bundle exists to prevent.
        if res and res.lower().startswith(("session", "plan")) and not _SOURCE_PATH.search(res):
            warns.append(
                "`sources` names a session/plan in prose, not a resolvable path -- cite the archived "
                "transcript (e.g. ai/session/raw/<session-id>.md) so the claim stays checkable"
            )
            continue
        # Path-check every file-like source. URLs are skipped: reachability needs the network, and a
        # chat URL that outlives its project reshuffle can't be proven from here either way.
        if res and "://" not in res:
            for m in _SOURCE_PATH.finditer(res):
                cand = m.group(1).replace("\\", "/")
                if "/" in cand and not (repo_root / cand).exists() and not Path(cand).is_absolute():
                    warns.append(f"`sources` path not found: {cand}")
                    break

    status = str(fm.get("status") or "").strip().lower()
    if status in ("deprecated", "stale") and not _superseded_by_resolving_relation(fm, path):
        # A deprecated note that points at its successor (a `supersedes`/`relates`/`duplicates`
        # relation whose target exists) is the normal end of a lifecycle -- e.g. an open-question
        # superseded by a decision note -- not rot. Only an orphaned deprecation needs a human.
        warns.append("status: deprecated with no resolving successor relation -- known wrong or "
                     "superseded; add `relations: [supersedes|relates <successor>]`, or delete")

    # trust: a stable note should carry a verified entry; entries need a spec-shaped actor + a date.
    entries = verified_list(fm)
    if status == "stable" and not entries:
        warns.append("status: stable but no `verified` entry -- promote with `okf --promote` "
                     "(adds the human: actor + date) rather than editing status by hand")
    latest = None
    for e in entries:
        by = str(e.get("by") or "").strip()
        if not by:
            warns.append("a `verified` entry has no `by` actor (spec requires {by, at})")
        elif not _ACTOR_RX.match(by):
            warns.append(f"`verified.by` '{by}' is not a spec actor (human:<id> | process:<id> | "
                         "<producer>/<version>)")
        d = _iso_date(e.get("at"))
        if d is None:
            warns.append("a `verified` entry has no parseable ISO `at` date")
        elif latest is None or d > latest:
            latest = d
    # lifecycle: explicit stale_after, else derive from the latest verification (confirm-or-decay).
    today_d = date.fromisoformat(today)
    sa = fm.get("stale_after")
    if sa not in (None, ""):
        sa_d = _iso_date(sa)
        if sa_d is None:
            warns.append("`stale_after` is not an ISO 8601 datetime")
        elif today_d >= sa_d:
            warns.append(f"stale_after {sa_d} has passed -- re-verify (okf --promote) or deprecate")
    elif latest is not None:
        age = (today_d - latest).days
        if age > STALE_AFTER_DAYS:
            warns.append(f"verified {age}d ago (>{STALE_AFTER_DAYS}d) -- re-confirm or it decays")

    # typed relations: each must be '<verb> <path>' with a known verb and a target that resolves.
    rels = fm.get("relations")
    if rels:
        for r in ([rels] if isinstance(rels, str) else rels):
            parts = str(r).strip().split(None, 1)
            if len(parts) != 2 or parts[0] not in RELATION_VERBS:
                warns.append(f"relation '{r}' must be '<verb> <path>', verb in {sorted(RELATION_VERBS)}")
                continue
            if not (path.parent / parts[1]).resolve().exists():
                warns.append(f"relation target not found: {parts[1]}")

    # YAML coercion traps: unquoted `description: no` -> bool False; `title: 2026` -> int;
    # an ISO date -> date object. Flag so the human quotes it (we can't recover the original text).
    for k in ("type", "title", "description"):
        v = fm.get(k)
        if v is not None and not isinstance(v, str):
            warns.append(f"`{k}` parsed as {type(v).__name__}, not text -- quote it in YAML "
                         "(unquoted yes/no/on/off become booleans; bare numbers/dates coerce)")
    return warns


_SUCCESSOR_VERBS = {"supersedes", "relates", "duplicates"}


def _superseded_by_resolving_relation(fm: dict, path: Path) -> bool:
    rels = fm.get("relations")
    for r in ([rels] if isinstance(rels, str) else (rels or [])):
        parts = str(r).strip().split(None, 1)
        if len(parts) == 2 and parts[0] in _SUCCESSOR_VERBS and (path.parent / parts[1]).exists():
            return True
    return False


def check_links(root: Path):
    """Every markdown .md link under `root` resolves to an existing file. Returns broken list."""
    broken = []
    for md in sorted(root.rglob("*.md")):
        if ".okf-backups" in md.parts:
            continue
        text = _read_text(md)
        if text is None:
            continue
        for m in _MD_LINK.finditer(text):
            target = m.group(1)
            if "://" in target:
                continue
            resolved = (md.parent / target).resolve() if not target.startswith("/") \
                else (root / target.lstrip("/")).resolve()
            if not resolved.exists():
                broken.append((md, target))
    return broken


# --------------------------------------------------------------------------- reindex

def _concepts_in(directory: Path, *, recursive: bool):
    it = directory.rglob("*.md") if recursive else directory.glob("*.md")
    out = []
    for p in sorted(it, key=lambda q: q.name):
        if p.name.lower() in RESERVED or ".okf-backups" in p.parts:
            continue
        text = _read_text(p)
        if text is None:
            continue                      # unreadable encoding -> leave out of the index, don't crash
        fm, _ = parse_frontmatter(text)
        out.append((p, fm or {}))
    return out


def _line(link: str, fm: dict) -> str:
    title = str(fm.get("title") or Path(link).stem)
    desc = str(fm.get("description") or "").strip()
    return f"* [{title}]({link})" + (f" - {desc}" if desc else "")


def _grouped_sections(concepts, base: Path) -> list[str]:
    lines: list[str] = []
    known = {k for k, _ in TYPE_HEADINGS}
    buckets = [(h, [(p, fm) for p, fm in concepts if str(fm.get("type", "")).strip() == k])
               for k, h in TYPE_HEADINGS]
    others = [(p, fm) for p, fm in concepts if str(fm.get("type", "")).strip() not in known]
    if others:
        buckets.append(("Other", others))
    for heading, items in buckets:
        if not items:
            continue
        lines.append(f"## {heading}")
        for p, fm in items:
            lines.append(_line(p.relative_to(base).as_posix(), fm))
        lines.append("")
    return lines


def _preamble(index_path: Path, default_title: str, *, force: bool):
    """(preamble_text, ok). ok=False means refuse: a non-empty index has no sentinel (would clobber)."""
    if index_path.exists():
        text = _read_text(index_path) or ""
        if AUTO_SENTINEL in text:
            return text.split(AUTO_SENTINEL)[0].rstrip(), True
        if text.strip() and not force:
            return text, False  # hand-edited, no sentinel -> caller refuses unless --force
    return f"# {default_title}", True


def _with_okf_version(preamble: str) -> str:
    """Ensure the bundle-root index preamble starts with the spec's `okf_version` frontmatter."""
    stripped = preamble.lstrip()
    if stripped.startswith(_FM_DELIM):
        fm, rest = parse_frontmatter(stripped)
        if fm is not None and "okf_version" in fm:
            return preamble
        if fm is not None:                 # frontmatter without the key: add it, keep the rest
            fm = {"okf_version": OKF_STANDARD_VERSION, **fm}
            return serialize(fm, rest).rstrip()
    return f"{OKF_VERSION_HEADER}\n\n{preamble}"


def reindex(bundle: Path, *, force: bool = False) -> list[Path]:
    """Generate root + nested index.md from concept frontmatter (OKF progressive disclosure).

    Preserves prose above AUTO_SENTINEL; refuses to clobber a non-empty index that lacks the
    sentinel unless force=True. Single level of topic subdirs (concepts may live at root too).
    The root index.md declares `okf_version` (spec v0.2) in a frontmatter block.
    """
    written: list[Path] = []
    skipped: list[Path] = []
    subdirs = sorted(d for d in bundle.iterdir() if d.is_dir())

    dir_entries = []
    for d in subdirs:
        concepts = _concepts_in(d, recursive=True)
        if not concepts:
            continue
        dir_entries.append((d, len(concepts)))
        idx = d / "index.md"
        pre, ok = _preamble(idx, d.name, force=force)
        if not ok:
            skipped.append(idx)
            continue
        body = [pre, "", AUTO_SENTINEL, ""] + _grouped_sections(concepts, d)
        idx.write_text("\n".join(body).rstrip() + "\n", encoding="utf-8")
        written.append(idx)

    root_concepts = _concepts_in(bundle, recursive=False)
    idx = bundle / "index.md"
    pre, ok = _preamble(idx, "Memory index", force=force)
    if ok:
        body = [_with_okf_version(pre), "", AUTO_SENTINEL, ""]
        if dir_entries:
            body.append("## Subdirectories")
            for d, n in dir_entries:
                body.append(f"* [{d.name}]({d.name}/index.md) - {n} notes")
            body.append("")
        if root_concepts:
            body.append("## Notes")
            for p, fm in root_concepts:
                body.append(_line(p.name, fm))
            body.append("")
        idx.write_text("\n".join(body).rstrip() + "\n", encoding="utf-8")
        written.append(idx)
    else:
        skipped.append(idx)

    for s in skipped:
        print(f"REFUSED to regenerate {s}: it has content but no '{AUTO_SENTINEL}' marker. "
              "Add the marker (content above it is preserved) or pass --force.")
    return written


def root_okf_version(bundle: Path):
    """The `okf_version` the bundle-root index.md declares, or None."""
    idx = bundle / "index.md"
    text = _read_text(idx) if idx.exists() else None
    if not text:
        return None
    fm, _ = parse_frontmatter(text)
    return str(fm.get("okf_version")) if fm and "okf_version" in fm else None


# --------------------------------------------------------------------------- move

def move_concept(src: Path, dst: Path, root: Path) -> list[Path]:
    """Move a note and rewrite every inbound markdown link under `root` (resolution-based).

    Guards: SRC must be an existing non-reserved concept; DST must not already exist.
    """
    if src.name.lower() in RESERVED:
        raise ValueError(f"refusing to move a reserved file: {src.name}")
    if dst.exists():
        raise FileExistsError(f"destination already exists: {dst}")
    src_abs = src.resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    dst_abs = dst.resolve()
    touched: list[Path] = []
    for md in sorted(root.rglob("*.md")):
        text = _read_text(md)
        if text is None:
            continue                      # can't safely rewrite links in a non-UTF-8 file

        def _rewrite(m):
            target, anchor = m.group(1), (m.group(2) or "")
            if "://" in target:
                return m.group(0)
            base = md.parent if not target.startswith("/") else root
            resolved = (base / target.lstrip("/")).resolve()
            if resolved != src_abs:
                return m.group(0)
            newrel = os.path.relpath(dst_abs, md.parent).replace(os.sep, "/")
            return f"]({newrel}{anchor})"

        new = _MD_LINK.sub(_rewrite, text)
        if new != text:
            md.write_text(new, encoding="utf-8")
            touched.append(md)
    return touched


# --------------------------------------------------------------------------- touch / promote

def touch_notes(paths: list[Path], *, today: str, actor: str = DEFAULT_ACTOR) -> list[Path]:
    """Bump `generated.at` (last meaningful change) to today; ensure `created` exists."""
    done = []
    for p in paths:
        text = _read_text(p)
        if text is None:
            print(f"[SKIP] {p}: unreadable (not UTF-8)")
            continue
        fm, body = parse_frontmatter(text)
        if fm is None:
            print(f"[SKIP] {p}: no frontmatter")
            continue
        gen = fm.get("generated") if isinstance(fm.get("generated"), dict) else {}
        prev_raw = gen.get("at") if gen.get("at") not in (None, "") else fm.get("timestamp")
        prev_at = _to_iso_dt(prev_raw) if prev_raw not in (None, "") else ""
        if not str(fm.get("created") or "").strip():
            fm["created"] = prev_at.split("T")[0] if prev_at else today
        fm.pop("timestamp", None)
        fm["generated"] = {"by": str(gen.get("by") or actor), "at": f"{today}T00:00:00Z"}
        p.write_text(serialize(fm, body), encoding="utf-8")
        done.append(p)
    return done


def promote_notes(paths: list[Path], *, actor: str, now: str | None = None) -> list[Path]:
    """Human promotion (the ONLY path that writes a verified entry): status -> stable, append
    verified {by: actor, at: now}, stale_after = now + STALE_AFTER_DAYS."""
    now = now or now_iso()
    done = []
    for p in paths:
        text = _read_text(p)
        if text is None:
            print(f"[SKIP] {p}: unreadable (not UTF-8)")
            continue
        fm, body = parse_frontmatter(text)
        if fm is None:
            print(f"[SKIP] {p}: no frontmatter")
            continue
        fm["status"] = "stable"
        fm.pop("verified_on", None)
        entries = verified_list(fm)
        entries.append({"by": actor, "at": now})
        fm["verified"] = entries
        fm["stale_after"] = _plus_days(now, STALE_AFTER_DAYS)
        p.write_text(serialize(fm, body), encoding="utf-8")
        done.append(p)
    return done


# --------------------------------------------------------------------------- topic hint

def _slug_token(stem: str) -> str:
    if "_" in stem:
        prefix, rest = stem.split("_", 1)
        if prefix in TYPE_ENUM:
            stem = rest
    return stem.split("-", 1)[0]


def _topic_hint(stems: list[str]) -> list[str]:
    tally: dict[str, int] = {}
    for s in stems:
        tok = _slug_token(s)
        tally[tok] = tally.get(tok, 0) + 1
    ranked = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    lines = [
        f"SUGGESTION: {len(stems)} concepts, flat, at/over the ~{FLAT_THRESHOLD} threshold "
        "-- consider foldering by topic (Phase 4 step 5).",
        "  Rough slug-token tally (a HINT only). The agent reads the notes and refines by",
        "  PLACEMENT -- moving whole files into topic folders (NEVER combining file contents):",
        "  put related domains in ONE folder, fix token accidents, keep domain-less notes at root.",
    ]
    clusters = [f"{tok} ({n})" for tok, n in ranked if n > 1]
    singles = [tok for tok, n in ranked if n == 1]
    if clusters:
        lines.append("    candidate clusters: " + ", ".join(clusters))
    if singles:
        lines.append(f"    singletons (likely belong in an existing cluster's folder, or stay at root): {', '.join(singles)}")
    return lines


# --------------------------------------------------------------------------- suggest-links

# Words too generic to signal a specific relationship (plus corpus-frequent terms are dropped below).
_LINK_STOP = set((
    "the a an and or of to in on for with is are was this that these those it its by as at "
    "use using used via from into per note notes new old fix when then than only not no yes "
    "you your our we run runs ran md ai memory project notes-about"
).split())


def _note_terms(p: Path, fm: dict) -> set[str]:
    """Salient lowercase terms for a note: de-typed slug tokens + title/description words + tags."""
    terms: set[str] = set()
    stem = p.stem
    if "_" in stem and stem.split("_", 1)[0] in TYPE_ENUM:
        stem = stem.split("_", 1)[1]
    text = f"{stem.replace('-', ' ')} {fm.get('title') or ''} {fm.get('description') or ''}".lower()
    for w in re.findall(r"[a-z][a-z0-9-]{2,}", text):
        terms.add(w)
    for t in (fm.get("tags") or []):
        terms.add(str(t).lower())
    return terms - _LINK_STOP


def _bundle_graph(bundle: Path):
    """Return (concepts: {resolved_path: (p, fm, terms)}, edges: set[frozenset{pathA,pathB}])."""
    raw = {}
    for p in sorted(bundle.rglob("*.md")):
        if p.name.lower() in RESERVED or ".okf-backups" in p.parts:
            continue
        text = _read_text(p)
        if text is None:
            continue
        fm, body = parse_frontmatter(text)
        raw[p.resolve()] = (p, fm or {}, body or "")
    edges: set = set()
    for rp, (p, fm, body) in raw.items():
        targets = []
        for m in _MD_LINK.finditer(body):                       # inline markdown links
            t = m.group(1)
            if "://" in t:
                continue
            targets.append((bundle / t.lstrip("/")).resolve() if t.startswith("/")
                            else (p.parent / t).resolve())
        rels = fm.get("relations")                              # typed relations
        if rels:
            for r in ([rels] if isinstance(rels, str) else rels):
                parts = str(r).strip().split(None, 1)
                if len(parts) == 2:
                    targets.append((p.parent / parts[1]).resolve())
        for res in targets:
            if res in raw and res != rp:
                edges.add(frozenset({rp, res}))
    concepts = {rp: (p, fm, _note_terms(p, fm)) for rp, (p, fm, body) in raw.items()}
    return concepts, edges


def suggest_links(bundle: Path, *, min_score: int = 2, limit: int = 25):
    """Surface note PAIRS that share salient terms but have NO existing link/relation (a HINT)."""
    concepts, edges = _bundle_graph(bundle)
    items = list(concepts.items())
    n = len(items)
    df: dict[str, int] = {}                                     # document frequency, to drop corpus-generic terms
    for _rp, (_p, _fm, terms) in items:
        for t in terms:
            df[t] = df.get(t, 0) + 1
    generic = {t for t, c in df.items() if c > max(2, n * 0.4)}
    cands = []
    for i in range(n):
        rpa, (pa, _fa, ta) = items[i]
        for j in range(i + 1, n):
            rpb, (pb, _fb, tb) = items[j]
            if frozenset({rpa, rpb}) in edges:
                continue
            shared = (ta & tb) - generic
            same_folder = pa.parent == pb.parent
            score = len(shared) + (1 if same_folder else 0)
            if shared and score >= min_score:
                cands.append((score, pa, pb, shared))
    cands.sort(key=lambda c: (-c[0], c[1].name, c[2].name))
    return cands[:limit]


# --------------------------------------------------------------------------- review

def review_drafts(bundle: Path):
    """Return [(path, fm)] for concepts whose status is `draft` (or legacy `unverified`) — the
    promotion queue.

    Read-only. This is the human-handoff for a backfill campaign: machine-derived notes land
    as status: draft, and a human promotes them (okf --promote) after checking sources/Verify.
    """
    rows = []
    for md in sorted(bundle.rglob("*.md")):
        if md.name.lower() in RESERVED or ".okf-backups" in md.parts:
            continue
        text = _read_text(md)
        if text is None:
            continue
        fm, _ = parse_frontmatter(text)
        if fm is None:
            continue
        if str(fm.get("status") or "").strip().lower() in ("draft", "unverified"):
            rows.append((md, fm))
    return rows


review_unverified = review_drafts   # back-compat alias for callers of the 0.8 name


# --------------------------------------------------------------------------- helpers

def find_git_root(start: Path):
    p = start.resolve()
    for cand in [p, *p.parents]:
        if (cand / ".git").exists():
            return cand
    return None


def backup_bundle(bundle: Path, *, today: str) -> Path:
    # OUTSIDE the bundle, so backups never pollute reindex / link checks / the viewer.
    dest = bundle.parent / ".okf-backups" / f"{bundle.name}-{today}"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for md in bundle.rglob("*.md"):
        if ".okf-backups" in md.parts:
            continue
        rel = md.relative_to(bundle)
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(md, dest / rel)
    return dest


# --------------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Normalize / check / maintain an ai/memory OKF bundle.")
    ap.add_argument("bundle", type=Path, nargs="?", help="bundle dir, e.g. ai/memory")
    ap.add_argument("--apply", action="store_true", help="rewrite frontmatter in place (migrates legacy keys)")
    ap.add_argument("--check", action="store_true",
                    help="strict report; exit 1 on ANY drift/error/warning/broken-link (for CI)")
    ap.add_argument("--gate", action="store_true",
                    help="like --check but exit 1 only on MECHANICAL drift (changes/errors/broken/"
                         "renames) — ignores soft provenance warnings; for a per-turn Stop hook")
    ap.add_argument("--reindex", action="store_true", help="regenerate index.md files, then exit")
    ap.add_argument("--review", action="store_true",
                    help="list concepts with status: draft (the promotion queue); read-only")
    ap.add_argument("--promote", nargs="+", metavar="PATH",
                    help="human promotion: status stable + verified {by: --actor, at: now} + stale_after")
    ap.add_argument("--suggest-links", action="store_true", dest="suggest_links",
                    help="surface note pairs sharing terms but not yet linked/related (a hint); read-only")
    ap.add_argument("--move", nargs=2, metavar=("SRC", "DST"), help="move a note + rewrite links")
    ap.add_argument("--touch", nargs="+", metavar="PATH", help="bump note generated.at to today")
    ap.add_argument("--actor", help="actor for generated.by / verified.by (default: ai/okf.conf "
                                    "`actor`, else human:<git user.name>, else human:unknown)")
    ap.add_argument("--root", type=Path, help="search root for --move link rewrite (default: repo/cwd)")
    ap.add_argument("--no-backup", action="store_true", help="skip the pre-apply backup")
    ap.add_argument("--force", action="store_true", help="override the reindex no-sentinel guard")
    ap.add_argument("--version", action="store_true", help="print tool + standard version")
    args = ap.parse_args(argv)
    _safe_stdio()                         # UTF-8 output regardless of console codepage
    today = today_iso()

    if args.version:
        print(f"okf_normalize tool {TOOL_VERSION}; OKF standard {OKF_STANDARD_VERSION}; lk {LK_VERSION}")
        return 0
    if args.bundle is None:
        ap.error("bundle is required")
    bundle: Path = args.bundle
    if not bundle.is_dir():
        print(f"ERROR: not a directory: {bundle}", file=sys.stderr)
        return 2
    actor = resolve_actor(bundle, args.actor)

    if args.touch:
        done = touch_notes([Path(p) for p in args.touch], today=today, actor=actor)
        print(f"touched {len(done)} note(s) -> generated.at {today}")
        return 0

    if args.promote:
        if not actor.startswith("human:"):
            print(f"okf --promote: refused -- actor '{actor}' is not a human: actor. Promotion is a "
                  "human act; pass --actor human:<id> or set `actor = human:<id>` in ai/okf.conf.",
                  file=sys.stderr)
            return 2
        done = promote_notes([Path(p) for p in args.promote], actor=actor)
        print(f"promoted {len(done)} note(s) -> status stable, verified by {actor}, "
              f"stale_after +{STALE_AFTER_DAYS}d")
        return 0

    if args.move:
        src, dst = Path(args.move[0]), Path(args.move[1])
        if not src.is_file():
            print(f"ERROR: not a file: {src}", file=sys.stderr)
            return 2
        root = args.root or find_git_root(bundle) or Path.cwd()
        try:
            touched = move_concept(src, dst, root)
        except (ValueError, FileExistsError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        print(f"moved {src} -> {dst}; rewrote links in {len(touched)} file(s).")
        print("Now run --reindex to refresh the index.")
        return 0

    if args.reindex:
        written = reindex(bundle, force=args.force)
        print(f"reindexed {len(written)} index.md file(s):")
        for p in written:
            print(f"  {p}")
        return 0

    if args.suggest_links:
        cands = suggest_links(bundle)
        print(f"LINK SUGGESTIONS -- {len(cands)} candidate pair(s) sharing terms but not yet linked")
        print("(a HINT; add a typed relation or inline link ONLY where a real relationship exists)\n")
        for score, pa, pb, shared in cands:
            print(f"  [{score}] {pa.relative_to(bundle).as_posix()}  <->  {pb.relative_to(bundle).as_posix()}")
            print(f"        shared: {', '.join(sorted(shared))}")
        return 0

    if args.review:
        rows = review_drafts(bundle)
        print(f"PROMOTION QUEUE -- {len(rows)} concept(s) with status: draft")
        print("(machine-derived; check each against its `sources` + `**Verify:**`, then "
              "`okf --promote <path>` -- never flip status by hand)\n")
        for md, fm in rows:
            print(f"  {md.relative_to(bundle).as_posix()}")
            print(f"      {str(fm.get('title') or '').strip()}")
            srcs = sources_list(fm)
            if srcs:
                print(f"      sources: {'; '.join(str(s.get('resource') or '') for s in srcs)}")
        return 0

    # ---- report / check / apply ----
    repo_root = find_git_root(bundle) or bundle.parent
    if args.apply and not args.no_backup and find_git_root(bundle) is None:
        dest = backup_bundle(bundle, today=today)
        print(f"NOT a git repo -- backed up notes to {dest} before --apply.\n")

    descriptions = load_index_descriptions(bundle)
    renames: list[str] = []
    stems: list[str] = []
    foldered = False
    n_files = n_changed = n_errors = n_warns = 0
    bundle_resolved = bundle.resolve()

    disk_names = {p.name for p in bundle.iterdir() if p.is_file()}
    if "INDEX.md" in disk_names and "index.md" not in disk_names:
        renames.append("INDEX.md -> index.md  (OKF reserved index file; fix all references)")

    for md in sorted(bundle.rglob("*.md")):
        if md.name.lower() in RESERVED or ".okf-backups" in md.parts:
            continue
        n_files += 1
        stems.append(md.stem)
        if md.parent.resolve() != bundle_resolved:
            foldered = True
        text = _read_text(md)
        if text is None:
            print(f"[ERROR] {md.relative_to(bundle)}: not valid UTF-8 -- re-save as UTF-8")
            n_errors += 1
            continue
        fm, body = parse_frontmatter(text)
        if fm is None:
            why = ("malformed YAML frontmatter -- quote any value containing ': ' (e.g. a source path)"
                   if text.lstrip().startswith(_FM_DELIM) else "no frontmatter block")
            print(f"[ERROR] {md.relative_to(bundle)}: {why}")
            n_errors += 1
            continue

        stem = md.stem
        if "_" not in stem or stem.split("_", 1)[0] not in TYPE_ENUM:
            renames.append(f"{md.name} -> TYPE_slug.md  (filename should start with a type prefix)")

        new_fm, changes, errors = normalize_fm(fm, descriptions, md.name, today=today, actor=actor)
        warns = check_provenance(new_fm, body, md, repo_root, today=today)

        if changes or errors or warns:
            print(f"\n{md.relative_to(bundle)}")
            for c in changes:
                print(f"  ~ {c}")
            for e in errors:
                print(f"  ! {e}")
            for w in warns:
                print(f"  ? {w}")
        n_errors += 1 if errors else 0
        n_warns += len(warns)
        if changes:
            n_changed += 1
            if args.apply and new_fm != fm:
                md.write_text(serialize(new_fm, body), encoding="utf-8")

    broken = check_links(bundle)
    for md, target in broken:
        print(f"  ? broken link in {md.relative_to(bundle)} -> {target}")

    declared = root_okf_version(bundle)
    version_hint = None
    if (bundle / "index.md").exists() and declared != OKF_STANDARD_VERSION:
        version_hint = (f"root index.md declares okf_version {declared or '(none)'}; this tool targets "
                        f"{OKF_STANDARD_VERSION} -- run --reindex to stamp it")

    print("\n" + "=" * 60)
    if renames:
        print("RENAMES (handled by the skill: mv + reference fixups via --move; then --reindex):")
        for r in renames:
            print(f"  -> {r}")
    if version_hint:
        print(f"HINT: {version_hint}")
    if not foldered and n_files >= FLAT_THRESHOLD:
        for line in _topic_hint(stems):
            print(line)
    mode = "APPLIED frontmatter rewrites" if args.apply else \
           ("STRICT CHECK" if args.check else ("GATE" if args.gate else "DRY RUN (no files changed)"))
    print(f"{mode}: {n_files} concepts, {n_changed} need/had frontmatter changes, "
          f"{n_errors} errors, {n_warns} provenance/link warnings, "
          f"{len(broken)} broken links, {len(renames)} renames pending.")
    if not args.apply and n_changed:
        print("Re-run with --apply to write the frontmatter changes (legacy keys migrate to OKF v0.2).")

    if args.gate:  # per-turn hook: only MECHANICAL drift the agent can auto-fix
        return 1 if (n_changed + n_errors + len(broken) + len(renames)) else 0
    if args.check:  # CI/manual: any drift/error/warning/rename/broken-link fails
        return 1 if (n_changed + n_errors + n_warns + len(broken) + len(renames)) else 0
    return 1 if n_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
