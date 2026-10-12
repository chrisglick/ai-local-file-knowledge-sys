#!/usr/bin/env python3
"""lk-doctor: one command that checks the lk knowledge system is installed and wired right, and
fixes the safe parts.

    python ~/.claude/skills/lk-doctor/lk_doctor.py                  # install checks (+ project, if cwd is one)
    python lk_doctor.py --repo CLONE --project DIR                  # + drift vs the clone, + project wiring
    python lk_doctor.py --json                                      # the same checks as JSON
    python lk_doctor.py --sync-from CLONE [--prune] [--yes]         # copy skills/lk-* over the install
    python lk_doctor.py --remove-legacy [--yes]                     # delete pre-rename unprefixed copies
    python lk_doctor.py --project DIR --fix-shims [--yes]           # point an old okf shim at lk-init-ai-workspace

Every fix verb is a dry run until --yes. Check output is one line per check (PASS / WARN / FAIL, or
INFO for a note that needs no action), a `fix:` hint under each WARN and FAIL, then a summary line.
Exit: 0 no FAIL, 1 any FAIL (or a fix that was refused or errored), 2 usage error.

pyyaml + stdlib only, and it imports no other skill: the doctor has to run when the thing it is
diagnosing is the broken part. So the small frontmatter and okf.conf readers below are its own copies
(the engines' are okf_normalize.parse_frontmatter and distill_transcript.read_mode).
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # the doctor must still run, and say so, when pyyaml is the missing piece
    yaml = None

TOOL_VERSION = "1.0.0"
TARGET_OKF_STANDARD = "0.2"

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"

EXPECTED_SKILLS = ("lk-init-ai-workspace", "lk-backfill-memory", "lk-end-session", "lk-audit-knowledge",
                   "lk-doctor", "lk-reference")
CORE_SKILLS = ("lk-init-ai-workspace", "lk-end-session")
NO_SKILL_MD = ("lk-reference",)  # a shared reference dir, not a skill
LEGACY_SKILLS = ("init-ai-workspace", "backfill-memory", "end-session", "reference")

HASH_SKIP_DIRS = {"__pycache__", ".pytest_cache"}
HASH_SKIP_SUFFIXES = (".pyc", ".pyo")

LEGACY_KEYS = ("timestamp", "updated", "source", "verified_on")
LEGACY_STATUS = ("unverified", "verified", "stale", "open", "closed")
V02_STATUS = ("draft", "stable", "deprecated")
RESERVED = {"index.md", "log.md"}
ARCHIVE_MODES = ("local", "shared", "off")
QUEUE_WARN_ABOVE = 25
MIN_CLEANUP_DAYS = 365
RECOMMENDED_CLEANUP_DAYS = 3650

# Claude Code's own slash commands, so a SKILL.md mentioning `/init` is not reported as a phantom.
BUILTIN_SLASH = frozenset({
    "add-dir", "agents", "bug", "clear", "compact", "config", "context", "cost", "doctor", "exit",
    "export", "help", "hooks", "ide", "init", "install-github-app", "login", "logout", "mcp", "memory",
    "model", "output-style", "permissions", "plugin", "pr-comments", "release-notes", "resume", "review",
    "rewind", "security-review", "status", "statusline", "terminal-setup", "todos", "upgrade", "usage",
    "vim",
})
# Bare filesystem roots (`/tmp`, `/etc`) match the slash-command shape but are paths, not phantoms;
# single letters are Git Bash drive mounts (`/c`).
FS_ROOTS = frozenset({"bin", "boot", "dev", "etc", "home", "lib", "mnt", "opt", "proc", "root", "run",
                      "sbin", "srv", "sys", "tmp", "usr", "var"})
SLASH_RE = re.compile(r"`/([a-z][a-z0-9-]*)`")
STD_RE = re.compile(r"""^OKF_STANDARD_VERSION\s*=\s*["']([^"']+)["']""", re.M)
_HOME_RE = re.compile(r"\$\{HOME\}|\$HOME(?![A-Za-z0-9_])")

# The project's okf shim, as lk-init-ai-workspace/okf.shim.sh writes it: the env vars that override
# its skill dir and its engine, and the engine file it runs from that skill dir.
OKF_SHIM, OKF_SKILL, OKF_SHIM_SRC = "ai/scripts/okf", "lk-init-ai-workspace", "okf.shim.sh"
OKF_SKILL_VAR, OKF_ENGINE_VAR, OKF_ENGINE = "OKF_SKILL_DIR", "OKF_NORMALIZE", "okf_normalize.py"


@dataclass
class Check:
    level: str
    name: str
    message: str
    hint: str = ""
    details: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- small helpers

def _safe_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _from_msys(s: str) -> str:
    """Git Bash spells C:\\x as /c/x; Python on Windows needs the drive form."""
    if os.name == "nt":
        m = re.match(r"^/([A-Za-z])(/|$)", s)
        if m:
            return f"{m.group(1).upper()}:/{s[3:]}"
    return s


def _home() -> Path:
    """$HOME as the bash shims see it, falling back to the OS home dir."""
    h = os.environ.get("HOME")
    return Path(_from_msys(h)) if h else Path.home()


def _fwd(p: Path) -> str:
    return str(p).replace("\\", "/")


def expand_path(raw: str, base: Path | None) -> Path:
    """Expand the shell-ish path a shim default or env override uses ($HOME, ~); relative to base."""
    s = raw.strip().strip('"').strip("'")
    s = _HOME_RE.sub(lambda _m: _fwd(_home()), s)
    if s == "~" or s.startswith("~/"):
        s = _fwd(_home()) + s[1:]
    p = Path(_from_msys(os.path.expandvars(s)))
    if not p.is_absolute() and base is not None:
        p = base / p
    return p


def _read(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _dirs(p: Path) -> list[Path]:
    try:
        return sorted(c for c in p.iterdir() if c.is_dir())
    except OSError:
        return []


def _list(items: list[str], limit: int = 6) -> str:
    s = ", ".join(items[:limit])
    return s + (f" (+{len(items) - limit} more)" if len(items) > limit else "")


def _frontmatter_lines(text: str) -> list[str] | None:
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i]
    return None


def parse_frontmatter(text: str) -> dict | None:
    """The frontmatter dict, or None when absent or unparseable. Never raises."""
    if yaml is None:
        return None
    block = _frontmatter_lines(text)
    if block is None:
        return None
    try:
        fm = yaml.safe_load("\n".join(block)) or {}
    except Exception:  # YAMLError, and ValueError from e.g. an impossible date: never crash on a bad note
        return None
    return fm if isinstance(fm, dict) else None


def skill_field(skill_dir: Path, key: str) -> str | None:
    """A top-level scalar from SKILL.md frontmatter, read by regex so it works without pyyaml."""
    text = _read(skill_dir / "SKILL.md")
    block = _frontmatter_lines(text) if text else None
    for line in block or []:
        m = re.match(rf"^{re.escape(key)}:\s*(.*?)\s*$", line)
        if m:
            return m.group(1).strip("'\"") or None
    return None


def read_conf(cfg: Path) -> dict[str, str]:
    """Flat `key = value` reader for ai/okf.conf: `#` comments dropped, key folded, value kept."""
    out: dict[str, str] = {}
    text = _read(cfg) if cfg.is_file() else None
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


def tree_hashes(root: Path) -> dict[str, str]:
    """sha256 of every file under root, keyed by posix relative path; caches are ignored."""
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in HASH_SKIP_DIRS)
        for f in sorted(filenames):
            if f.endswith(HASH_SKIP_SUFFIXES):
                continue
            p = Path(dirpath) / f
            rel = p.relative_to(root).as_posix()
            try:
                out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError:
                out[rel] = "unreadable"
    return out


def compare_trees(installed: Path, repo: Path) -> dict:
    a, b = tree_hashes(installed), tree_hashes(repo)
    return {
        "changed": sorted(k for k in a.keys() & b.keys() if a[k] != b[k]),
        "only_repo": sorted(b.keys() - a.keys()),
        "only_installed": sorted(a.keys() - b.keys()),
        "files": len(b),
    }


def _describe(diff: dict) -> str:
    segs = [f"{label}: {_list(diff[key])}" for key, label in
            (("changed", "changed"), ("only_repo", "only in repo"), ("only_installed", "only installed"))
            if diff[key]]
    return "; ".join(segs)


def legacy_skill_in(path: str | None) -> str | None:
    """The legacy skill name a path runs through (`.../skills/init-ai-workspace/...`), if any."""
    parts = [p for p in re.split(r"[\\/]+", path or "") if p]
    for prev, part in zip(parts, parts[1:]):
        if prev == "skills" and part in LEGACY_SKILLS:
            return part
    return None


def is_lk_legacy(d: Path) -> bool:
    """A pre-rename copy of OUR skill, not some other skill that only shares the name."""
    if not d.is_dir():
        return False
    if d.name == "reference":
        return (d / "transcript-safety.md").is_file()
    return skill_field(d, "name") == d.name


def legacy_installs(skills_dir: Path) -> list[str]:
    return [n for n in LEGACY_SKILLS if is_lk_legacy(skills_dir / n)]


def repo_skills_dir(repo: Path) -> Path | None:
    """The clone's skills/ dir (also accepts being pointed at skills/ itself)."""
    for cand in (repo / "skills", repo):
        if any(d.name.startswith("lk-") for d in _dirs(cand)):
            return cand
    return None


def _lk_dirs(skills: Path) -> list[Path]:
    return [d for d in _dirs(skills) if d.name.startswith("lk-")]


def _sync_hint(repo: Path | None) -> str:
    if repo:
        return f"lk_doctor.py --sync-from {repo} --yes  (run it once without --yes to see the file list)"
    return "lk_doctor.py --sync-from <lk repo clone> --yes  (or: cp -r <clone>/skills/lk-* ~/.claude/skills/)"


# --------------------------------------------------------------------------- install checks

def check_skills_present(skills_dir: Path, repo: Path | None) -> list[Check]:
    out = []
    for name in EXPECTED_SKILLS:
        d, label = skills_dir / name, f"skill {name}"
        miss = FAIL if name in CORE_SKILLS else WARN
        if not d.is_dir():
            old = name[len("lk-"):]
            extra = (f" (legacy `{old}` is installed instead: the lk- rename needs a re-install)"
                     if is_lk_legacy(skills_dir / old) else "")
            out.append(Check(miss, label, f"not installed{extra}", _sync_hint(repo)))
        elif name in NO_SKILL_MD:
            out.append(Check(PASS, label, "installed (shared reference dir)"))
        elif not (d / "SKILL.md").is_file():
            out.append(Check(miss, label, "installed but SKILL.md is missing (a broken copy)", _sync_hint(repo)))
        else:
            v = skill_field(d, "version")
            out.append(Check(PASS, label, f"installed, version {v}") if v else
                       Check(WARN, label, "installed but SKILL.md has no `version:` (a copy from before lk 1.0.0)",
                             _sync_hint(repo)))
    return out


def check_legacy(skills_dir: Path) -> Check:
    legacy = legacy_installs(skills_dir)
    if not legacy:
        return Check(PASS, "legacy installs", "no pre-rename unprefixed copies")
    return Check(WARN, "legacy installs",
                 f"pre-rename copies still installed: {', '.join(legacy)}. They shadow the lk- skills (two "
                 f"skills answer the same trigger) and old shims keep running their stale engines",
                 "lk_doctor.py --remove-legacy --yes  (deletes each only once its lk- counterpart is installed)",
                 {"legacy": legacy})


def check_drift(skills_dir: Path, repo: Path | None, repo_skills: Path | None, env_note: str) -> list[Check]:
    if repo_skills is None:
        why = env_note or "skipped: no lk repo clone to compare the install against"
        return [Check(WARN, "repo drift", why,
                      "pass --repo <your ai-local-file-knowledge-sys clone>, or set LK_REPO_DIR to it")]
    out = []
    for src in _lk_dirs(repo_skills):
        inst = skills_dir / src.name
        if not inst.is_dir():
            continue  # the presence check already reported it
        diff = compare_trees(inst, src)
        iv, rv = skill_field(inst, "version"), skill_field(src, "version")
        n = len(diff["changed"]) + len(diff["only_repo"]) + len(diff["only_installed"])
        if n == 0 and iv == rv:
            out.append(Check(PASS, f"drift {src.name}", f"matches repo ({diff['files']} files)"))
            continue
        parts = []
        if iv != rv:
            parts.append(f"version {iv or 'none'} installed vs {rv or 'none'} in repo")
        if n:
            parts.append(f"{n} file(s) differ from repo: {_describe(diff)}")
        out.append(Check(WARN, f"drift {src.name}", "; ".join(parts), _sync_hint(repo), diff))
    for old in legacy_installs(skills_dir):
        src = repo_skills / f"lk-{old}"
        if not src.is_dir():
            continue
        diff = compare_trees(skills_dir / old, src)
        if diff["changed"] or diff["only_repo"] or diff["only_installed"]:
            out.append(Check(WARN, f"drift {old} (legacy)", f"differs from repo lk-{old}: {_describe(diff)}",
                             f"lk_doctor.py --sync-from {repo} --yes, then lk_doctor.py --remove-legacy --yes",
                             diff))
    return out


def check_normalizer(skills_dir: Path, repo: Path | None) -> Check:
    name = "normalizer"
    p = skills_dir / "lk-init-ai-workspace" / "okf_normalize.py"
    text = _read(p) if p.is_file() else None
    if text is None:
        note = ""
        legacy_text = _read(skills_dir / "init-ai-workspace" / "okf_normalize.py")
        if legacy_text is not None:
            m = STD_RE.search(legacy_text)
            note = f" (the legacy init-ai-workspace copy claims OKF standard {m.group(1) if m else '?'})"
        return Check(FAIL, name, f"lk-init-ai-workspace/okf_normalize.py not found{note}", _sync_hint(repo))
    m = STD_RE.search(text)
    if not m:
        return Check(WARN, name, "no OKF_STANDARD_VERSION line in lk-init-ai-workspace/okf_normalize.py",
                     _sync_hint(repo))
    if m.group(1) != TARGET_OKF_STANDARD:
        return Check(WARN, name, f"okf_normalize.py claims OKF standard {m.group(1)}; lk {TOOL_VERSION} targets "
                                 f"{TARGET_OKF_STANDARD}", _sync_hint(repo))
    return Check(PASS, name, f"okf_normalize.py targets OKF standard {m.group(1)}")


def check_slash_refs(skills_dir: Path, repo_skills: Path | None) -> list[Check]:
    files = [d / "SKILL.md" for d in _lk_dirs(skills_dir)]
    files += [skills_dir / n / "SKILL.md" for n in legacy_installs(skills_dir)]
    files = [f for f in files if f.is_file()]
    commands = _home() / ".claude" / "commands"
    known = {d.name for d in _dirs(skills_dir)} | BUILTIN_SLASH
    known |= {p.stem for p in commands.glob("*.md")} if commands.is_dir() else set()
    in_repo = {d.name for d in _lk_dirs(repo_skills)} if repo_skills else set()
    found: dict[str, list[str]] = {}
    for f in files:
        for i, line in enumerate((_read(f) or "").splitlines(), 1):
            for m in SLASH_RE.finditer(line):
                if m.group(1) not in known and m.group(1) not in FS_ROOTS and len(m.group(1)) > 1:
                    found.setdefault(m.group(1), []).append(f"{f.parent.name}/SKILL.md:{i}")
    if not files:
        return [Check(INFO, "slash refs", "no lk SKILL.md files installed to scan")]
    if not found:
        return [Check(PASS, "slash refs", f"no phantom slash references in {len(files)} SKILL.md file(s)")]
    out = []
    for name, where in sorted(found.items()):
        alt = f"lk-{name}"
        if alt in known:
            hint = f"did you mean `/{alt}`? fix the reference in the SKILL.md"
        elif alt in in_repo:
            hint = f"did you mean `/{alt}`? fix the reference, and install {alt} (it is in the repo)"
        else:
            hint = "fix the reference in the SKILL.md, or install the skill it names"
        out.append(Check(WARN, "slash refs", f"`/{name}` is not an installed skill or command ({_list(where, 4)})",
                         hint, {"name": name, "where": where}))
    return out


def probe_shim_python() -> tuple[str | None, bool]:
    """Mirror the shims' interpreter pick (first of python3/python/py that really runs), then ask it for
    yaml. Returns (command or None, can_import_yaml)."""
    code = "try:\n    import yaml\n    y = 1\nexcept Exception:\n    y = 0\nprint(42, y)"
    for cmd in ("python3", "python", "py"):
        exe = shutil.which(cmd)
        if not exe:
            continue
        try:
            r = subprocess.run([exe, "-c", code], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        parts = (r.stdout or "").split()
        if len(parts) == 2 and parts[0] == "42":
            return cmd, parts[1] == "1"
    return None, False


def check_python() -> list[Check]:
    exe = sys.executable
    if yaml is None:
        first = Check(FAIL, "python", f"pyyaml is not importable by {exe}", f'"{exe}" -m pip install pyyaml')
    else:
        first = Check(PASS, "python", f"{sys.version.split()[0]} with pyyaml "
                                      f"{getattr(yaml, '__version__', '?')} ({exe})")
    cmd, has_yaml = probe_shim_python()
    if cmd is None:
        second = Check(FAIL, "shim python", "none of python3, python, py runs a real interpreter, so "
                                            f"{OKF_SHIM} exits 127",
                       "install Python, or turn off the Microsoft Store alias (Settings > Apps > Advanced app "
                       "settings > App execution aliases)")
    elif not has_yaml:
        second = Check(FAIL, "shim python", f"`{cmd}` (the interpreter the okf shim picks first) cannot import yaml",
                       f"{cmd} -m pip install pyyaml")
    else:
        second = Check(PASS, "shim python", f"`{cmd}` runs and imports yaml")
    return [first, second]


def check_cleanup_period() -> Check:
    p = _home() / ".claude" / "settings.json"
    name = "cleanupPeriodDays"
    hint = (f'set "cleanupPeriodDays": {RECOMMENDED_CLEANUP_DAYS} in {p}: transcripts older than it are pruned '
            f"at startup, and /lk-backfill-memory cannot mine what is gone")
    if not p.is_file():
        return Check(WARN, name, f"unset ({p} not found): Claude Code's default is 30 days", hint)
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        return Check(WARN, name, f"could not parse {p}: {e}", hint)
    v = data.get("cleanupPeriodDays") if isinstance(data, dict) else None
    if v is None:
        return Check(WARN, name, "unset: Claude Code's default is 30 days", hint)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return Check(WARN, name, f"is {v!r}, not a number", hint)
    if v < MIN_CLEANUP_DAYS:
        return Check(WARN, name, f"is {v} days (below {MIN_CLEANUP_DAYS})", hint)
    return Check(PASS, name, f"is {v} days")


def check_install(skills_dir: Path, repo: Path | None, repo_skills: Path | None, env_note: str) -> list[Check]:
    return [*check_skills_present(skills_dir, repo),
            check_legacy(skills_dir),
            *check_drift(skills_dir, repo, repo_skills, env_note),
            check_normalizer(skills_dir, repo),
            *check_slash_refs(skills_dir, repo_skills),
            *check_python(),
            check_cleanup_period()]


# --------------------------------------------------------------------------- project checks

def check_conf(project: Path) -> Check:
    cfg = project / "ai" / "okf.conf"
    if not cfg.is_file():
        return Check(WARN, "okf.conf", "ai/okf.conf missing: tools fall back to archive = local",
                     "run /lk-init-ai-workspace (it writes ai/okf.conf from the template)")
    archive = read_conf(cfg).get("archive")
    if archive is None:
        return Check(PASS, "okf.conf archive", "archive unset (tools default to local)")
    if archive.lower() in ARCHIVE_MODES:
        return Check(PASS, "okf.conf archive", f"archive = {archive}")
    return Check(WARN, "okf.conf archive", f"archive = {archive} is not one of local|shared|off; tools fall "
                                           f"back to local", "set `archive = local` in ai/okf.conf (the "
                                                             "comments in that file explain shared/off)")


def parse_shim(text: str) -> tuple[str | None, str]:
    """(skill-dir default, engine path relative to the skill dir) as written in the okf shim."""
    m = re.search(r"\$\{%s:-((?:\$\{[^}]*\}|[^}])*)\}" % OKF_SKILL_VAR, text)
    e = re.search(r"\$\{%s:-\$\{?SKILL\}?/([^}]*)\}" % OKF_ENGINE_VAR, text)
    return (m.group(1) if m else None), (e.group(1) if e else OKF_ENGINE)


def check_shim(project: Path) -> Check:
    name, path = "okf shim", project / OKF_SHIM
    if not path.is_file():
        return Check(WARN, name, f"{OKF_SHIM} missing", "run /lk-init-ai-workspace (it installs the shim)")
    default, engine_rel = parse_shim(_read(path) or "")
    legacy_default = legacy_skill_in(default)
    if os.environ.get(OKF_ENGINE_VAR):
        engine, via = expand_path(os.environ[OKF_ENGINE_VAR], project), f"${OKF_ENGINE_VAR}"
    elif os.environ.get(OKF_SKILL_VAR):
        engine, via = expand_path(os.environ[OKF_SKILL_VAR], project) / engine_rel, f"${OKF_SKILL_VAR}"
    elif default is not None:
        engine, via = expand_path(default, project) / engine_rel, "shim default"
    else:
        return Check(WARN, name, f"could not find the ${{{OKF_SKILL_VAR}:-...}} default in {OKF_SHIM} "
                                 f"(hand-edited shim?)", f"re-copy {OKF_SKILL}/{OKF_SHIM_SRC} over {OKF_SHIM}")
    fix_hint = f"lk_doctor.py --project {project} --fix-shims --yes"
    if not engine.is_file():
        hint = (fix_hint if via == "shim default" and legacy_default else
                f"install the {OKF_SKILL} skill (lk_doctor.py --sync-from <lk repo clone> --yes), or set "
                f"{OKF_SKILL_VAR}")
        return Check(FAIL, name, f"{OKF_SHIM} -> engine not found at {engine} ({via})", hint)
    legacy = legacy_skill_in(str(engine))
    if legacy:
        return Check(WARN, name, f"{OKF_SHIM} -> {engine} runs the legacy `{legacy}` install ({via}); it breaks "
                                 f"once the legacy copies are removed",
                     fix_hint if via == "shim default" else f"point {via} at the {OKF_SKILL} dir")
    note = f"; the shim default still names legacy `{legacy_default}` (--fix-shims updates it)" if legacy_default else ""
    return Check(PASS, name, f"{OKF_SHIM} -> {engine} ({via}){note}")


def scan_bundle(bundle: Path) -> dict:
    st = {"notes": 0, "unparseable": [], "legacy_keys": Counter(), "legacy_status": Counter(),
          "legacy_notes": 0, "bad_status": {}, "draft": 0}
    for p in sorted(bundle.rglob("*.md")):
        if p.name.lower() in RESERVED or ".okf-backups" in p.parts:
            continue
        rel = p.relative_to(bundle).as_posix()
        st["notes"] += 1
        fm = parse_frontmatter(_read(p) or "")
        if fm is None:
            st["unparseable"].append(rel)
            continue
        keys = [k for k in LEGACY_KEYS if k in fm]
        st["legacy_keys"].update(keys)
        status = None if fm.get("status") is None else str(fm["status"]).strip()
        if status in LEGACY_STATUS:
            st["legacy_status"][status] += 1
        if keys or status in LEGACY_STATUS:
            st["legacy_notes"] += 1
        if status == "draft":
            st["draft"] += 1
        if status is not None and status not in V02_STATUS:
            st["bad_status"].setdefault(status, []).append(rel)
    return st


def _counts(c: Counter) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))


def check_bundle(bundle: Path) -> list[Check]:
    if not bundle.is_dir():
        return [Check(WARN, "bundle", "ai/memory missing", "run /lk-init-ai-workspace")]
    if yaml is None:
        return [Check(WARN, "bundle", "bundle checks skipped: pyyaml is missing", "pip install pyyaml")]
    st = scan_bundle(bundle)
    out = []
    if st["legacy_keys"]:
        msg = (f"{st['legacy_notes']} of {st['notes']} notes use pre-v0.2 vocabulary (keys: "
               f"{_counts(st['legacy_keys'])}")
        msg += f"; status: {_counts(st['legacy_status'])})" if st["legacy_status"] else ")"
        odd = sorted(set(st["bad_status"]) - set(LEGACY_STATUS))
        if odd:
            msg += f"; unmappable status values: {', '.join(odd)}"
        out.append(Check(WARN, "bundle vocabulary", msg,
                         "run ai/scripts/okf --apply to migrate to OKF v0.2 (lk-doctor does not migrate)",
                         {"legacy_keys": dict(st["legacy_keys"]), "legacy_status": dict(st["legacy_status"])}))
    elif st["bad_status"]:
        n = sum(len(v) for v in st["bad_status"].values())
        listing = "; ".join(f"{s}: {_list(files, 4)}" for s, files in sorted(st["bad_status"].items()))
        out.append(Check(FAIL, "bundle vocabulary",
                         f"{n} note(s) have a status outside draft|stable|deprecated ({listing})",
                         "OKF v0.2 allows only draft|stable|deprecated: run ai/scripts/okf --apply to map legacy "
                         "values, or fix the listed notes by hand", {"bad_status": st["bad_status"]}))
    else:
        out.append(Check(PASS, "bundle vocabulary", f"{st['notes']} notes, all OKF v0.2 vocabulary"))
    if st["unparseable"]:
        out.append(Check(WARN, "bundle frontmatter",
                         f"{len(st['unparseable'])} note(s) have no parseable frontmatter: {_list(st['unparseable'])}",
                         "run ai/scripts/okf --check for the exact error per note", {"files": st["unparseable"]}))
    out.append(_check_index(bundle))
    queue = st["draft"] + st["legacy_status"]["unverified"]
    if queue > QUEUE_WARN_ABOVE:
        out.append(Check(WARN, "promotion queue",
                         f"{queue} notes awaiting human review (draft {st['draft']}, legacy unverified "
                         f"{st['legacy_status']['unverified']}); above {QUEUE_WARN_ABOVE}",
                         "/lk-audit-knowledge to triage them (ai/scripts/okf --review lists them)"))
    else:
        out.append(Check(PASS, "promotion queue", f"{queue} notes awaiting review"))
    return out


def _check_index(bundle: Path) -> Check:
    idx = bundle / "index.md"
    hint = 'ai/scripts/okf --reindex  (writes okf_version: "0.2" into the root index)'
    if not idx.is_file():
        return Check(WARN, "index okf_version", "ai/memory/index.md missing", hint)
    fm = parse_frontmatter(_read(idx) or "")
    ver = fm.get("okf_version") if fm else None
    if ver is None:
        return Check(WARN, "index okf_version", "ai/memory/index.md has no okf_version frontmatter", hint)
    if str(ver) != TARGET_OKF_STANDARD:
        return Check(WARN, "index okf_version", f"okf_version is {ver}, expected {TARGET_OKF_STANDARD}", hint)
    return Check(PASS, "index okf_version", f'okf_version: "{ver}"')


def check_project(project: Path) -> list[Check]:
    return [check_conf(project), check_shim(project), *check_bundle(project / "ai" / "memory")]


# --------------------------------------------------------------------------- fix verbs

def plan_sync(repo_skills: Path, skills_dir: Path, prune: bool) -> list[tuple[str, str, Path, Path]]:
    ops = []
    for src_dir in _lk_dirs(repo_skills):
        dst_dir = skills_dir / src_dir.name
        src_h = tree_hashes(src_dir)
        dst_h = tree_hashes(dst_dir) if dst_dir.is_dir() else {}
        for rel in sorted(src_h):
            if rel not in dst_h or dst_h[rel] != src_h[rel]:
                ops.append(("add" if rel not in dst_h else "update", f"{src_dir.name}/{rel}",
                            src_dir / rel, dst_dir / rel))
        for rel in sorted(dst_h.keys() - src_h.keys()):
            ops.append(("delete" if prune else "keep", f"{src_dir.name}/{rel}", dst_dir / rel, dst_dir / rel))
    return ops


def fix_sync(repo_skills: Path, skills_dir: Path, prune: bool, yes: bool) -> tuple[int, list[str]]:
    words = {"add": ("would add", "added"), "update": ("would update", "updated"),
             "delete": ("would delete", "deleted")}
    lines, rc = [f"sync-from: {repo_skills} -> {skills_dir}"], 0
    ops = plan_sync(repo_skills, skills_dir, prune)
    for op, rel, src, dst in ops:
        if op == "keep":
            lines.append(f"  kept          {rel}  (only in the install; --prune deletes it)")
            continue
        if yes:
            try:
                if op == "delete":
                    dst.unlink()
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
            except OSError as e:
                lines.append(f"  ERROR         {rel}: {e}")
                rc = 1
                continue
        lines.append(f"  {words[op][1 if yes else 0]:<13} {rel}" + ("  (--prune)" if op == "delete" else ""))
    n = Counter(op for op, *_ in ops)
    if not any(n[k] for k in ("add", "update", "delete")):
        lines.append("sync-from: the installed lk-* skills already match the repo" +
                     (f" ({n['keep']} install-only file(s) kept)" if n["keep"] else ""))
    else:
        lines.append(f"sync-from: {n['add']} to add, {n['update']} to update, {n['delete']} to delete, "
                     f"{n['keep']} install-only kept. " +
                     ("Written." if yes else "DRY RUN: nothing written; add --yes to write."))
    return rc, lines


def _rmtree(d: Path) -> None:
    if d.is_symlink():
        d.unlink()
        return

    def _writable_retry(func, path, _exc):
        os.chmod(path, stat.S_IWRITE)
        func(path)

    shutil.rmtree(d, onerror=_writable_retry)


def fix_remove_legacy(skills_dir: Path, yes: bool, will_install: set[str]) -> tuple[int, list[str]]:
    present = legacy_installs(skills_dir)
    if not present:
        return 0, [f"remove-legacy: no legacy unprefixed lk installs in {skills_dir}"]
    lines, rc = ["remove-legacy:"], 0
    for old in present:
        d, lk = skills_dir / old, f"lk-{old}"
        if not (skills_dir / lk).is_dir() and lk not in will_install:
            rc = 1
            lines.append(f"  kept          {d}  ({lk} is not installed: install it first with --sync-from "
                         f"<lk repo clone>)")
        elif not yes:
            why = "is installed" if (skills_dir / lk).is_dir() else "would be installed by the sync above"
            lines.append(f"  would remove  {d}  ({lk} {why})")
        else:
            try:
                _rmtree(d)
                lines.append(f"  removed       {d}")
            except OSError as e:
                rc = 1
                lines.append(f"  ERROR         removing {d}: {e}")
    if not yes:
        lines.append("remove-legacy: DRY RUN: nothing removed; add --yes to delete.")
    return rc, lines


def rewrite_shim_default(text: str) -> str:
    """Rename a legacy skill dir to its lk- name inside the okf shim's one `${OKF_SKILL_DIR:-default}`."""
    legacy = "|".join(re.escape(n) for n in LEGACY_SKILLS)

    def repl(m):
        new_default = re.sub(rf"(?<=skills[/\\])({legacy})(?=[/\\]?$)", lambda mm: f"lk-{mm.group(1)}", m.group(2))
        return m.group(1) + new_default + m.group(3)

    return re.sub(r"(\$\{%s:-)((?:\$\{[^}]*\}|[^}])*)(\})" % OKF_SKILL_VAR, repl, text)


def fix_shims(project: Path, yes: bool) -> tuple[int, list[str]]:
    path = project / OKF_SHIM
    text = path.read_bytes().decode("utf-8", errors="surrogateescape") if path.is_file() else None  # keep CRLF
    new = rewrite_shim_default(text) if text is not None else None
    if new == text:
        return 0, [f"fix-shims: nothing to fix ({OKF_SHIM} is absent, or its default names no legacy skill dir)"]
    lines = [f"fix-shims: {path}"]
    lines += [f"    {d}" for d in difflib.unified_diff(text.splitlines(), new.splitlines(), f"a/{OKF_SHIM}",
                                                        f"b/{OKF_SHIM}", n=0, lineterm="")]
    if not yes:
        return 0, [*lines, "fix-shims: DRY RUN: nothing written; add --yes to write."]
    try:
        path.write_bytes(new.encode("utf-8", errors="surrogateescape"))
    except OSError as e:
        return 1, [*lines, f"  ERROR writing {path}: {e}"]
    return 0, [*lines, f"  rewrote {path}"]


# --------------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lk_doctor.py",
        description="Check that the lk knowledge-system skills are installed and wired right; fix the safe parts.",
        epilog="Exit codes: 0 no FAIL, 1 any FAIL (or a fix refused), 2 usage error. "
               "Fix verbs are dry runs until --yes.")
    p.add_argument("--skills-dir", metavar="DIR", help="installed skills dir (default: $CLAUDE_SKILLS_DIR, "
                                                       "else ~/.claude/skills)")
    p.add_argument("--repo", metavar="CLONE", help="lk repo clone to compare the install against (default: "
                                                   "$LK_REPO_DIR; skipped if neither)")
    p.add_argument("--project", metavar="DIR", help="project to check (default: cwd, if it has ai/memory or "
                                                    "ai/okf.conf)")
    p.add_argument("--json", action="store_true", help="emit the checks as JSON")
    g = p.add_argument_group("fix verbs (dry run unless --yes; they run instead of the checks)")
    g.add_argument("--sync-from", metavar="CLONE", help="copy skills/lk-* from CLONE over the installed skills")
    g.add_argument("--prune", action="store_true", help="with --sync-from: also delete install-only files")
    g.add_argument("--remove-legacy", action="store_true",
                   help="delete unprefixed pre-rename copies whose lk- counterpart is installed")
    g.add_argument("--fix-shims", action="store_true",
                   help="point the project's ai/scripts/okf default at the lk-init-ai-workspace dir")
    g.add_argument("--yes", action="store_true", help="actually write (fix verbs only)")
    p.add_argument("--version", action="version", version=f"lk_doctor {TOOL_VERSION}")
    return p


def _resolve_repo(parser, args) -> tuple[Path | None, Path | None, str]:
    for flag, val in (("--sync-from", args.sync_from), ("--repo", args.repo)):
        if val:
            rs = repo_skills_dir(Path(val))
            if rs is None:
                parser.error(f"{flag} {val}: no skills/lk-* dirs there (expected an ai-local-file-knowledge-sys clone)")
    val = args.sync_from or args.repo
    if val:
        return Path(val), repo_skills_dir(Path(val)), ""
    env = os.environ.get("LK_REPO_DIR")
    if env:
        rs = repo_skills_dir(Path(_from_msys(env)))
        if rs is None:
            return None, None, f"skipped: LK_REPO_DIR={env} has no skills/lk-* dirs"
        return Path(_from_msys(env)), rs, ""
    return None, None, ""


def _run(parser, args) -> int:
    fixing = bool(args.sync_from or args.remove_legacy or args.fix_shims)
    if args.yes and not fixing:
        parser.error("--yes only applies to a fix verb (--sync-from, --remove-legacy, --fix-shims)")
    if args.prune and not args.sync_from:
        parser.error("--prune only applies with --sync-from")
    if args.skills_dir and not Path(args.skills_dir).is_dir() and not args.sync_from:
        parser.error(f"--skills-dir {args.skills_dir}: not a directory")
    if args.project and not Path(args.project).is_dir():
        parser.error(f"--project {args.project}: not a directory")
    if args.skills_dir:
        skills_dir = Path(args.skills_dir)
    elif os.environ.get("CLAUDE_SKILLS_DIR"):
        skills_dir = Path(_from_msys(os.environ["CLAUDE_SKILLS_DIR"]))
    else:
        skills_dir = _home() / ".claude" / "skills"
    repo, repo_skills, env_note = _resolve_repo(parser, args)
    cwd = Path.cwd()
    if args.project:
        project = Path(args.project)
    elif (cwd / "ai" / "memory").is_dir() or (cwd / "ai" / "okf.conf").is_file():
        project = cwd
    else:
        project = None

    if fixing:
        if args.fix_shims and project is None:
            parser.error("--fix-shims needs a project: pass --project DIR, or run from a project root "
                         "(one with ai/memory or ai/okf.conf)")
        rc, lines, will_install = 0, [], set()
        if args.sync_from:
            r, ls = fix_sync(repo_skills, skills_dir, args.prune, args.yes)
            rc, lines = max(rc, r), lines + ls
            if not args.yes:
                will_install = {d.name for d in _lk_dirs(repo_skills)}
        if args.remove_legacy:
            r, ls = fix_remove_legacy(skills_dir, args.yes, will_install)
            rc, lines = max(rc, r), lines + ls
        if args.fix_shims:
            r, ls = fix_shims(project, args.yes)
            rc, lines = max(rc, r), lines + ls
        if args.json:
            print(json.dumps({"tool": "lk-doctor", "version": TOOL_VERSION, "dry_run": not args.yes,
                              "lines": lines, "exit_code": rc}, indent=2, ensure_ascii=False))
        else:
            print("\n".join(lines))
        return rc

    checks = check_install(skills_dir, repo, repo_skills, env_note)
    if project is not None:
        checks += check_project(project)
    else:
        checks.append(Check(INFO, "project", "no project checks: the cwd has no ai/memory or ai/okf.conf "
                                             "(pass --project DIR to check one)"))
    counts = Counter(c.level for c in checks)
    rc = 1 if counts[FAIL] else 0
    if args.json:
        print(json.dumps({"tool": "lk-doctor", "version": TOOL_VERSION, "skills_dir": str(skills_dir),
                          "repo": str(repo) if repo else None, "project": str(project) if project else None,
                          "checks": [asdict(c) for c in checks],
                          "summary": {k: counts[k] for k in (PASS, WARN, FAIL, INFO)}, "exit_code": rc},
                         indent=2, ensure_ascii=False))
        return rc
    print(f"lk-doctor {TOOL_VERSION}  skills: {skills_dir}  repo: {repo or '(none)'}  "
          f"project: {project or '(none)'}")
    for c in checks:
        print(f"{c.level:<4}  {c.name}: {c.message}")
        if c.hint and c.level in (WARN, FAIL):
            print(f"      fix: {c.hint}")
    print(f"lk-doctor: {counts[PASS]} PASS, {counts[WARN]} WARN, {counts[FAIL]} FAIL"
          + (f", {counts[INFO]} INFO" if counts[INFO] else ""))
    return rc


def main(argv=None) -> int:
    _safe_stdio()
    parser = build_parser()
    try:
        return _run(parser, parser.parse_args(argv))
    except SystemExit as e:  # argparse: --help/--version exit 0, usage errors exit 2
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 2)


if __name__ == "__main__":
    sys.exit(main())
