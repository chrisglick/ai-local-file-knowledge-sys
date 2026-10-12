"""Docs-versus-code contract for the lk skills.

Three of the five skills are prose (instructions a model follows), so they cannot be unit-tested.
What CAN rot, and did, is the contract between that prose and the code it tells the agent to run:
a flag that never existed (`--doctor-age`), a slash command nobody wrote (`/audit-knowledge`),
a template a phase says to copy that was deleted. This file turns each of those into a red test.

Run from the repo root: `python -m pytest -q`  (or just `python -m pytest -q tests`).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
SKILL_DIRS = sorted(p for p in SKILLS.iterdir() if p.is_dir() and p.name.startswith("lk-"))
SKILL_MDS = [d / "SKILL.md" for d in SKILL_DIRS if (d / "SKILL.md").exists()]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

# Scripts the docs may tell the agent to run, and where their argparse lives.
SCRIPTS = {
    "okf_normalize.py": SKILLS / "lk-init-ai-workspace" / "okf_normalize.py",
    "distill_transcript.py": SKILLS / "lk-init-ai-workspace" / "distill_transcript.py",
    "lk_doctor.py": SKILLS / "lk-doctor" / "lk_doctor.py",
    "audit_knowledge.py": SKILLS / "lk-audit-knowledge" / "audit_knowledge.py",
}
# The project shim (`ai/scripts/okf`, written as `okf` in prose) forwards to the normalizer and
# adds two verbs of its own that dispatch to the viewer / distiller.
SHIM_ONLY_FLAGS = {"--render", "--distill"}

# Claude Code built-ins a SKILL.md may legitimately mention as `/name`, plus bare filesystem roots
# that look like slash commands in backticks but are paths (`/tmp`, `/dev/null`).
BUILTIN_SLASH = {"init", "clear", "compact", "help", "config", "memory", "hooks", "status",
                 "doctor", "resume", "model", "login", "logout", "review",
                 "tmp", "dev", "etc", "usr", "var", "home", "bin", "opt", "mnt", "proc"}

_FENCE = re.compile(r"```.*?```", re.S)
_SLASH = re.compile(r"`/([a-z][a-z0-9-]*)`")
_MD_LINK = re.compile(r"\]\(([^)#:\s]+\.md)\)")
_EXAMPLE_LINK = re.compile(r"type_slug|\*|_x\.md|runbook_refresh|crm/|topic/")


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.relative_to(ROOT)}: no frontmatter"
    end = text.index("\n---", 4)
    return yaml.safe_load(text[4:end]) or {}


def _argparse_flags(script: Path) -> set[str]:
    src = script.read_text(encoding="utf-8")
    return set(re.findall(r'add_argument\(\s*"(--[a-z-]+)"', src))


def _doc_files() -> list[Path]:
    out = [ROOT / "README.md", ROOT / "KNOWLEDGE-SYSTEM.md"]
    for d in SKILL_DIRS:
        out += [p for p in d.rglob("*.md") if ".okf-backups" not in p.parts]
    return out


# --------------------------------------------------------------------------- frontmatter

@pytest.mark.parametrize("skill_md", SKILL_MDS, ids=lambda p: p.parent.name)
def test_skill_frontmatter_names_itself_and_carries_the_release_version(skill_md: Path):
    fm = _frontmatter(skill_md)
    assert fm.get("name") == skill_md.parent.name, "SKILL.md `name:` must equal its directory name"
    assert str(fm.get("version")) == VERSION, f"`version:` must match the repo VERSION file ({VERSION})"
    assert str(fm.get("description") or "").strip(), "`description:` is empty"


def test_every_lk_dir_except_reference_has_a_skill_md():
    missing = [d.name for d in SKILL_DIRS if d.name != "lk-reference" and not (d / "SKILL.md").exists()]
    assert not missing, missing


# --------------------------------------------------------------------------- slash commands

@pytest.mark.parametrize("skill_md", SKILL_MDS, ids=lambda p: p.parent.name)
def test_slash_commands_in_skill_docs_name_real_skills(skill_md: Path):
    """`/audit-knowledge` and `/resume-session` lived in these files for months. Never again."""
    text = _FENCE.sub("", skill_md.read_text(encoding="utf-8"))
    installed = {d.name for d in SKILL_DIRS}
    bad = sorted({name for name in _SLASH.findall(text)
                  if name not in installed and name not in BUILTIN_SLASH})
    assert not bad, f"{skill_md.relative_to(ROOT)} mentions slash commands that do not exist: {bad}"


@pytest.mark.parametrize("doc", [ROOT / "README.md", ROOT / "KNOWLEDGE-SYSTEM.md"], ids=lambda p: p.name)
def test_lk_slash_commands_in_root_docs_exist(doc: Path):
    text = _FENCE.sub("", doc.read_text(encoding="utf-8"))
    installed = {d.name for d in SKILL_DIRS}
    bad = sorted({n for n in _SLASH.findall(text) if n.startswith("lk-") and n not in installed})
    assert not bad, f"{doc.name} mentions lk skills that do not exist: {bad}"


# --------------------------------------------------------------------------- script flags

def _flag_mentions(text: str):
    """Yield (script_key, flag) for every `<script> ... --flag` mention inside one backtick span."""
    for span in re.findall(r"`([^`\n]+)`", text):
        key = None
        for name in SCRIPTS:
            if name in span:
                key = name
        if key is None and re.search(r"(^|[\s/])okf(\s|$)", span):
            key = "okf"
        if key is None:
            continue
        for flag in re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", span):
            yield key, flag


def test_every_flag_the_docs_mention_exists_in_the_script():
    """`--doctor-age` was documented in lk-end-session for a flag the engine never had."""
    valid = {k: _argparse_flags(v) for k, v in SCRIPTS.items()}
    valid["okf"] = valid["okf_normalize.py"] | valid["distill_transcript.py"] | SHIM_ONLY_FLAGS
    problems = []
    for doc in _doc_files():
        for key, flag in _flag_mentions(doc.read_text(encoding="utf-8")):
            if flag not in valid[key]:
                problems.append(f"{doc.relative_to(ROOT)}: `{key} {flag}` (no such flag)")
    assert not problems, "\n".join(problems)


# --------------------------------------------------------------------------- links and templates

def test_relative_markdown_links_in_docs_resolve():
    problems = []
    for doc in _doc_files():
        if doc.name.endswith(".template.md"):
            continue                     # templates hold example links for the project they scaffold
        text = _FENCE.sub("", doc.read_text(encoding="utf-8"))
        for target in _MD_LINK.findall(text):
            if _EXAMPLE_LINK.search(target):
                continue
            if not (doc.parent / target).resolve().exists():
                problems.append(f"{doc.relative_to(ROOT)} -> {target}")
    assert not problems, "broken relative links:\n" + "\n".join(problems)


def test_templates_the_init_skill_says_to_copy_exist():
    """A phase that says 'copy X.template.md' must have an X.template.md beside it."""
    skill_dir = SKILLS / "lk-init-ai-workspace"
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    named = set(re.findall(r"`([A-Za-z0-9_.-]+\.template(?:\.md)?)`", text))
    missing = sorted(n for n in named if not (skill_dir / n).exists())
    assert not missing, f"lk-init-ai-workspace/SKILL.md names templates that are not shipped: {missing}"


def test_normalizer_and_doctor_agree_on_the_okf_standard_version():
    """lk-doctor warns when the installed normalizer is not on the standard it expects."""
    norm = (SCRIPTS["okf_normalize.py"]).read_text(encoding="utf-8")
    doctor = (SCRIPTS["lk_doctor.py"]).read_text(encoding="utf-8")
    std = re.search(r'OKF_STANDARD_VERSION\s*=\s*"([^"]+)"', norm).group(1)
    assert std in doctor, f"lk_doctor.py never mentions the normalizer's OKF standard {std}"
