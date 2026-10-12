"""Tests for lk_doctor.py. Run from the repo root: python -m pytest -q skills/lk-doctor
(deps: pytest, pyyaml).

Import the module directly, call main([...]) in-process, and assert on exit codes, printed lines
and on-disk results under tmp_path. Every test runs against a fake HOME (the `env` fixture) so
nothing reads or writes the real ~/.claude.
"""
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import lk_doctor as doc


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _skill_md(name: str, version: str | None = "1.0.0", body: str = "") -> str:
    v = f"version: {version}\n" if version else ""
    return f"---\nname: {name}\n{v}description: test skill {name}\n---\n\n# {name}\n\n{body}\n"


def make_repo(root: Path) -> Path:
    """A fake lk repo clone: every expected skill and a v0.2 normalizer."""
    skills = root / "skills"
    for name in doc.EXPECTED_SKILLS:
        if name == "lk-reference":
            _write(skills / name / "transcript-safety.md", "# transcript safety\n")
            continue
        _write(skills / name / "SKILL.md",
               _skill_md(name, body="Run `/lk-end-session` at the close; pipe noise to `/dev/null`. "
                                    "The built-in `/init` is different."))
    _write(skills / "lk-init-ai-workspace" / "okf_normalize.py",
           'TOOL_VERSION = "0.9"\nOKF_STANDARD_VERSION = "0.2"\n')
    return root


def install(repo: Path, skills_dir: Path, names=doc.EXPECTED_SKILLS) -> None:
    skills_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copytree(repo / "skills" / name, skills_dir / name)


def install_legacy(skills_dir: Path, names=doc.LEGACY_SKILLS) -> None:
    """Pre-rename copies, as the old README's `cp -r skills/*` left them."""
    for name in names:
        if name == "reference":
            _write(skills_dir / name / "transcript-safety.md", "# old transcript safety\n")
            continue
        _write(skills_dir / name / "SKILL.md", _skill_md(name, version=None,
                                                          body="See `/audit-knowledge`."))
    if "init-ai-workspace" in names:
        _write(skills_dir / "init-ai-workspace" / "okf_normalize.py", 'OKF_STANDARD_VERSION = "0.1"\n')


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    claude = home / ".claude"
    skills = claude / "skills"
    skills.mkdir(parents=True)
    _write(claude / "settings.json", json.dumps({"cleanupPeriodDays": 3650}))
    monkeypatch.setenv("HOME", str(home))
    for var in ("CLAUDE_SKILLS_DIR", "LK_REPO_DIR", "OKF_SKILL_DIR", "OKF_NORMALIZE"):
        monkeypatch.delenv(var, raising=False)
    # The real probe shells out to python3/python/py; keep tests hermetic.
    monkeypatch.setattr(doc, "probe_shim_python", lambda: ("python", True))
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    repo = make_repo(tmp_path / "repo")
    return SimpleNamespace(tmp=tmp_path, home=home, claude=claude, skills=skills, repo=repo, work=work)


def run(capsys, *argv):
    rc = doc.main([str(a) for a in argv])
    return rc, capsys.readouterr().out


def lines(out: str, level: str, *needles: str) -> list[str]:
    return [ln for ln in out.splitlines()
            if ln.startswith(level) and all(n in ln for n in needles)]


# ---- project fixtures ----

def shim(skill_dir_default: str) -> str:
    """An ai/scripts/okf shim whose default skill dir is ~/.claude/skills/<skill_dir_default>."""
    return ("#!/usr/bin/env bash\nset -euo pipefail\n"
            f'SKILL="${{OKF_SKILL_DIR:-$HOME/.claude/skills/{skill_dir_default}}}"\n'
            'ENGINE="${OKF_NORMALIZE:-$SKILL/okf_normalize.py}"\n'
            'if [ ! -f "$ENGINE" ]; then echo "engine not found at $ENGINE" >&2; exit 127; fi\n'
            'exec python "$ENGINE" "$@"\n')


LEGACY_NOTE = """---
type: decision
title: Old style
timestamp: '2026-07-01'
source: src/x.py
status: unverified
---

Body. **Verify:** read src/x.py
"""

V02_NOTE = """---
type: decision
title: New style
generated:
  by: claude-code/test-model
  at: '2026-10-12T00:00:00Z'
sources:
  - resource: src/x.py
status: {status}
---

Body. **Verify:** read src/x.py
"""

INDEX_V02 = '---\nokf_version: "0.2"\n---\n# Memory Index\n'


def make_project(root: Path, *, okf="lk-init-ai-workspace", conf="archive = local\n", notes=None,
                 index=INDEX_V02) -> Path:
    mem = root / "ai" / "memory"
    mem.mkdir(parents=True)
    if conf is not None:
        _write(root / "ai" / "okf.conf", conf)
    if okf is not None:
        _write(root / "ai" / "scripts" / "okf", shim(okf))
    if index is not None:
        _write(mem / "index.md", index)
    for name, text in (notes or {}).items():
        _write(mem / name, text)
    return root


# ---- resolution and exit codes ----

def test_healthy_install_without_repo_passes_and_warns_how_to_enable_repo_checks(env, capsys):
    install(env.repo, env.skills)
    rc, out = run(capsys)
    assert rc == 0
    assert not lines(out, "FAIL")
    skip = lines(out, "WARN", "repo")
    assert skip and "--repo" in out and "LK_REPO_DIR" in out
    assert lines(out, "INFO", "project")  # no project resolved from an empty cwd
    assert "0 FAIL" in out.splitlines()[-1]


def test_skills_dir_comes_from_env_when_no_flag(env, capsys, monkeypatch):
    other = env.tmp / "elsewhere" / "skills"
    install(env.repo, other)
    monkeypatch.setenv("CLAUDE_SKILLS_DIR", str(other))
    rc, out = run(capsys)
    assert rc == 0
    assert str(other) in out


def test_repo_comes_from_env_when_no_flag(env, capsys, monkeypatch):
    install(env.repo, env.skills)
    monkeypatch.setenv("LK_REPO_DIR", str(env.repo))
    rc, out = run(capsys)
    assert rc == 0
    assert lines(out, "PASS", "drift lk-end-session", "matches repo")


def test_missing_core_skill_fails_and_missing_optional_skill_warns(env, capsys):
    install(env.repo, env.skills, names=[n for n in doc.EXPECTED_SKILLS
                                         if n not in ("lk-end-session", "lk-audit-knowledge")])
    rc, out = run(capsys, "--skills-dir", env.skills)
    assert rc == 1
    assert lines(out, "FAIL", "lk-end-session", "not installed")
    assert lines(out, "WARN", "lk-audit-knowledge", "not installed")


def test_usage_errors_exit_2(env, capsys):
    assert doc.main(["--no-such-flag"]) == 2
    assert doc.main(["--repo", str(env.tmp / "nope")]) == 2
    assert doc.main(["--skills-dir", str(env.tmp / "nope")]) == 2
    assert doc.main(["--yes"]) == 2                       # --yes without a fix verb
    assert doc.main(["--prune"]) == 2                     # --prune without --sync-from
    assert doc.main(["--fix-shims"]) == 2                 # no project resolvable from cwd


def test_help_exits_zero(env, capsys):
    assert doc.main(["--help"]) == 0
    assert "--sync-from" in capsys.readouterr().out


def test_json_output_lists_checks_and_summary(env, capsys):
    install(env.repo, env.skills)
    rc, out = run(capsys, "--json", "--repo", env.repo)
    data = json.loads(out)
    assert rc == data["exit_code"] == 0
    assert {"level", "name", "message", "hint"} <= set(data["checks"][0])
    assert data["summary"]["FAIL"] == 0
    assert data["repo"] == str(env.repo)


# ---- install-level checks ----

def test_expected_skills_are_exactly_the_lk_dirs_this_package_ships():
    shipped = {d.name for d in Path(__file__).resolve().parent.parent.iterdir()
               if d.is_dir() and d.name.startswith("lk-")}
    assert set(doc.EXPECTED_SKILLS) == shipped


def test_every_legacy_name_has_an_lk_counterpart():
    # --remove-legacy deletes a copy only once its lk- counterpart is installed: a legacy name
    # without one would be flagged forever and never removable.
    assert all(f"lk-{name}" in doc.EXPECTED_SKILLS for name in doc.LEGACY_SKILLS)


def test_legacy_unprefixed_installs_are_named_with_the_remove_legacy_hint(env, capsys):
    install(env.repo, env.skills)
    install_legacy(env.skills, names=["backfill-memory", "end-session"])
    rc, out = run(capsys)
    warn = lines(out, "WARN", "legacy")
    assert warn and "backfill-memory" in warn[0] and "end-session" in warn[0]
    assert "--remove-legacy" in out


def test_core_skill_installed_only_under_legacy_name_says_so(env, capsys):
    install_legacy(env.skills, names=["end-session"])
    rc, out = run(capsys)
    assert rc == 1
    fail = lines(out, "FAIL", "lk-end-session")
    assert fail and "end-session" in fail[0] and "legacy" in fail[0]


def test_drifted_file_and_version_are_reported_with_sync_hint(env, capsys):
    install(env.repo, env.skills)
    ws = env.skills / "lk-init-ai-workspace"
    _write(ws / "okf_normalize.py", 'TOOL_VERSION = "0.8"\nOKF_STANDARD_VERSION = "0.2"\n')
    _write(ws / "SKILL.md", _skill_md("lk-init-ai-workspace", version="0.9.0"))
    _write(ws / "__pycache__" / "okf_normalize.cpython-311.pyc", "junk")
    rc, out = run(capsys, "--repo", env.repo)
    warn = lines(out, "WARN", "drift lk-init-ai-workspace")
    assert warn
    assert "okf_normalize.py" in warn[0] and "0.9.0" in warn[0] and "1.0.0" in warn[0]
    assert "__pycache__" not in out
    assert f"--sync-from {env.repo}" in out
    assert lines(out, "PASS", "lk-end-session", "matches repo")


def test_legacy_copy_is_compared_against_its_lk_counterpart_in_the_repo(env, capsys):
    install(env.repo, env.skills)
    install_legacy(env.skills, names=["init-ai-workspace"])
    rc, out = run(capsys, "--repo", env.repo)
    warn = lines(out, "WARN", "init-ai-workspace (legacy)")
    assert warn and "okf_normalize.py" in warn[0] and "lk-init-ai-workspace" in warn[0]


def test_skill_md_without_version_warns(env, capsys):
    install(env.repo, env.skills)
    _write(env.skills / "lk-backfill-memory" / "SKILL.md", _skill_md("lk-backfill-memory", version=None))
    rc, out = run(capsys)
    assert lines(out, "WARN", "lk-backfill-memory", "version")


def test_normalizer_on_old_standard_warns_and_missing_normalizer_fails(env, capsys):
    install(env.repo, env.skills)
    norm = env.skills / "lk-init-ai-workspace" / "okf_normalize.py"
    norm.write_text('OKF_STANDARD_VERSION = "0.1"\n', encoding="utf-8")
    rc, out = run(capsys)
    assert rc == 0
    assert lines(out, "WARN", "0.1", "0.2")
    norm.unlink()
    rc, out = run(capsys)
    assert rc == 1
    assert lines(out, "FAIL", "okf_normalize.py")


def test_phantom_slash_refs_are_flagged_and_real_paths_and_builtins_are_not(env, capsys):
    install(env.repo, env.skills, names=[n for n in doc.EXPECTED_SKILLS if n != "lk-audit-knowledge"])
    _write(env.skills / "lk-end-session" / "SKILL.md",
           _skill_md("lk-end-session", body="Then run `/audit-knowledge` and `/resume-session`.\n"
                                            "Not `/tmp` nor `/dev/null`; `/lk-init-ai-workspace` is real; "
                                            "so is `/grill-me`."))
    _write(env.skills / "grill-me" / "SKILL.md", _skill_md("grill-me"))
    rc, out = run(capsys, "--repo", env.repo)
    assert lines(out, "WARN", "/audit-knowledge", "lk-end-session/SKILL.md:")
    assert lines(out, "WARN", "/resume-session")
    assert "/lk-audit-knowledge" in out           # suggests the lk- name that exists in the repo
    for real in ("/tmp", "/dev", "/lk-init-ai-workspace", "/grill-me", "/init", "/lk-end-session"):
        assert not lines(out, "WARN", f"`{real}`")


def test_phantom_scan_also_reads_legacy_copies(env, capsys):
    install(env.repo, env.skills)
    install_legacy(env.skills, names=["end-session"])
    rc, out = run(capsys)
    assert lines(out, "WARN", "/audit-knowledge", "end-session/SKILL.md")


def test_missing_pyyaml_fails(env, capsys, monkeypatch):
    install(env.repo, env.skills)
    monkeypatch.setattr(doc, "yaml", None)
    rc, out = run(capsys)
    assert rc == 1
    assert lines(out, "FAIL", "pyyaml")


def test_shim_python_without_yaml_fails(env, capsys, monkeypatch):
    install(env.repo, env.skills)
    monkeypatch.setattr(doc, "probe_shim_python", lambda: ("python3", False))
    rc, out = run(capsys)
    assert rc == 1
    assert lines(out, "FAIL", "python3", "yaml")


@pytest.mark.parametrize("settings,level", [
    ({}, "WARN"),
    ({"cleanupPeriodDays": 30}, "WARN"),
    ({"cleanupPeriodDays": 3650}, "PASS"),
])
def test_cleanup_period_days(env, capsys, settings, level):
    install(env.repo, env.skills)
    _write(env.claude / "settings.json", json.dumps(settings))
    rc, out = run(capsys)
    assert lines(out, level, "cleanupPeriodDays")


def test_malformed_user_settings_does_not_crash(env, capsys):
    install(env.repo, env.skills)
    _write(env.claude / "settings.json", "{ not json")
    rc, out = run(capsys)
    assert rc == 0
    assert lines(out, "WARN", "cleanupPeriodDays")


# ---- project-level checks ----

def test_project_from_cwd_when_it_has_ai_memory(env, capsys, monkeypatch):
    install(env.repo, env.skills)
    proj = make_project(env.tmp / "proj")
    monkeypatch.chdir(proj)
    rc, out = run(capsys)
    assert rc == 0
    assert lines(out, "PASS", "okf shim")


def test_old_shim_with_no_legacy_install_fails_engine_not_found(env, capsys):
    install(env.repo, env.skills)
    proj = make_project(env.tmp / "proj", okf="init-ai-workspace")
    rc, out = run(capsys, "--project", proj)
    assert rc == 1
    fail = lines(out, "FAIL", "okf shim")
    assert fail and "init-ai-workspace" in fail[0]
    assert "--fix-shims" in out


def test_old_shim_that_still_resolves_to_a_legacy_install_warns(env, capsys):
    install(env.repo, env.skills)
    install_legacy(env.skills, names=["init-ai-workspace"])
    proj = make_project(env.tmp / "proj", okf="init-ai-workspace")
    rc, out = run(capsys, "--project", proj)
    warn = lines(out, "WARN", "okf shim")
    assert warn and "legacy" in warn[0]


def test_shim_honours_skill_dir_env_override(env, capsys, monkeypatch):
    install(env.repo, env.skills)
    proj = make_project(env.tmp / "proj", okf="init-ai-workspace")
    monkeypatch.setenv("OKF_SKILL_DIR", str(env.skills / "lk-init-ai-workspace"))
    rc, out = run(capsys, "--project", proj)
    assert lines(out, "PASS", "okf shim", "OKF_SKILL_DIR")


def test_okf_conf_archive_mode_is_checked_and_a_missing_conf_warns(env, capsys):
    install(env.repo, env.skills)
    proj = make_project(env.tmp / "proj", conf="archive = public  # typo\n")
    rc, out = run(capsys, "--project", proj)
    assert lines(out, "WARN", "archive", "public")
    conf = proj / "ai" / "okf.conf"
    conf.write_text("archive = shared\n", encoding="utf-8")
    rc, out = run(capsys, "--project", proj)
    assert lines(out, "PASS", "archive = shared")
    conf.unlink()
    rc, out = run(capsys, "--project", proj)
    assert lines(out, "WARN", "okf.conf", "missing")


def test_project_checks_cover_only_the_lk_wiring(env):
    """Other tools' scripts, okf.conf keys and Claude Code hooks are not lk-doctor's business."""
    install(env.repo, env.skills)
    proj = make_project(env.tmp / "proj", conf="archive = local\nother_tool_key = x\n")
    _write(proj / "ai" / "scripts" / "other-tool", "#!/bin/sh\nexit 0\n")
    _write(proj / ".claude" / "settings.json",
           json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "sh gone.sh"}]}]}}))
    assert [c.name for c in doc.check_project(proj)] == [
        "okf.conf archive", "okf shim", "bundle vocabulary", "index okf_version", "promotion queue"]


def test_legacy_bundle_vocabulary_warns_with_counts_and_migration_hint(env, capsys):
    install(env.repo, env.skills)
    notes = {f"decision_{i}.md": LEGACY_NOTE for i in range(3)}
    notes["broken.md"] = "---\ntitle: [unclosed\n---\nbody\n"
    proj = make_project(env.tmp / "proj", notes=notes, index="# Memory Index\n")
    rc, out = run(capsys, "--project", proj)
    warn = lines(out, "WARN", "vocabulary")
    assert warn and "timestamp 3" in warn[0] and "unverified 3" in warn[0]
    assert "ai/scripts/okf --apply" in out
    assert lines(out, "WARN", "frontmatter", "broken.md")
    assert lines(out, "WARN", "okf_version")
    assert "--reindex" in out


def test_v02_bundle_with_invalid_status_fails(env, capsys):
    install(env.repo, env.skills)
    proj = make_project(env.tmp / "proj", notes={
        "decision_good.md": V02_NOTE.format(status="stable"),
        "decision_bad.md": V02_NOTE.format(status="open"),
    })
    rc, out = run(capsys, "--project", proj)
    assert rc == 1
    fail = lines(out, "FAIL", "status")
    assert fail and "decision_bad.md" in fail[0] and "open" in fail[0]


def test_clean_v02_bundle_passes_vocabulary_and_index(env, capsys):
    install(env.repo, env.skills)
    proj = make_project(env.tmp / "proj", notes={"decision_a.md": V02_NOTE.format(status="draft")})
    _write(proj / "ai" / "memory" / "log.md", "---\nstatus: whatever\n---\nlog\n")  # reserved: skipped
    rc, out = run(capsys, "--project", proj)
    assert rc == 0
    assert lines(out, "PASS", "vocabulary")
    assert lines(out, "PASS", "okf_version")


def test_promotion_queue_above_threshold_warns_with_audit_hint(env, capsys):
    install(env.repo, env.skills)
    notes = {f"decision_{i}.md": V02_NOTE.format(status="draft") for i in range(doc.QUEUE_WARN_ABOVE + 1)}
    proj = make_project(env.tmp / "proj", notes=notes)
    rc, out = run(capsys, "--project", proj)
    assert lines(out, "WARN", "promotion queue", str(doc.QUEUE_WARN_ABOVE + 1))
    assert "/lk-audit-knowledge" in out


def test_no_project_is_informational_only(env, capsys):
    install(env.repo, env.skills)
    rc, out = run(capsys)
    assert rc == 0
    assert not lines(out, "WARN", "okf shim")
    assert lines(out, "INFO", "project")


# ---- fix verb: --sync-from ----

def test_sync_dry_run_lists_changes_and_writes_nothing(env, capsys):
    install(env.repo, env.skills, names=["lk-init-ai-workspace", "lk-end-session"])
    norm = env.skills / "lk-init-ai-workspace" / "okf_normalize.py"
    _write(norm, "drifted\n")
    _write(env.repo / "skills" / "lk-init-ai-workspace" / "__pycache__" / "x.pyc", "junk")
    rc, out = run(capsys, "--sync-from", env.repo)
    assert rc == 0
    assert "would update" in out and "lk-init-ai-workspace/okf_normalize.py" in out
    assert "would add" in out and "lk-doctor/SKILL.md" in out
    assert "__pycache__" not in out
    assert "--yes" in out
    assert norm.read_text(encoding="utf-8") == "drifted\n"
    assert not (env.skills / "lk-doctor").exists()


def test_sync_with_yes_writes_and_keeps_install_only_files_unless_pruned(env, capsys):
    ws = env.skills / "lk-init-ai-workspace"
    install(env.repo, env.skills, names=["lk-init-ai-workspace"])
    _write(ws / "okf_normalize.py", "drifted\n")
    _write(ws / "local_only.py", "mine\n")
    rc, out = run(capsys, "--sync-from", env.repo, "--yes")
    assert rc == 0
    assert (ws / "okf_normalize.py").read_bytes() == \
        (env.repo / "skills" / "lk-init-ai-workspace" / "okf_normalize.py").read_bytes()
    assert (env.skills / "lk-doctor" / "SKILL.md").is_file()
    assert (ws / "local_only.py").is_file()
    assert "local_only.py" in out and "--prune" in out

    rc, out = run(capsys, "--sync-from", env.repo, "--prune")
    assert "would delete" in out and (ws / "local_only.py").is_file()
    rc, out = run(capsys, "--sync-from", env.repo, "--prune", "--yes")
    assert rc == 0
    assert not (ws / "local_only.py").exists()

    rc, out = run(capsys, "--repo", env.repo)
    assert not lines(out, "WARN", "differ")


# ---- fix verb: --remove-legacy ----

def test_remove_legacy_dry_run_then_yes_removes_only_those_with_lk_counterparts(env, capsys):
    install(env.repo, env.skills, names=["lk-init-ai-workspace", "lk-reference"])
    install_legacy(env.skills, names=["init-ai-workspace", "end-session", "reference"])
    rc, out = run(capsys, "--remove-legacy")
    assert rc == 1                                   # end-session has no lk- counterpart
    assert f"would remove  {env.skills / 'init-ai-workspace'}" in out
    assert (env.skills / "init-ai-workspace").is_dir()

    rc, out = run(capsys, "--remove-legacy", "--yes")
    assert rc == 1
    assert not (env.skills / "init-ai-workspace").exists()
    assert not (env.skills / "reference").exists()
    assert (env.skills / "end-session").is_dir()
    assert "lk-end-session" in out


def test_remove_legacy_leaves_a_foreign_dir_that_only_shares_the_name(env, capsys):
    install(env.repo, env.skills, names=["lk-reference"])
    _write(env.skills / "reference" / "someone-elses-notes.md", "not ours\n")
    rc, out = run(capsys, "--remove-legacy", "--yes")
    assert rc == 0
    assert (env.skills / "reference").is_dir()
    assert "no legacy" in out


def test_remove_legacy_dry_run_counts_skills_a_planned_sync_will_install(env, capsys):
    install_legacy(env.skills, names=["backfill-memory"])
    rc, out = run(capsys, "--sync-from", env.repo, "--remove-legacy")
    assert rc == 0
    assert "would remove" in out


# ---- fix verb: --fix-shims ----

def test_fix_shims_dry_run_prints_diff_and_yes_rewrites_only_the_default(env, capsys):
    install(env.repo, env.skills)
    proj = make_project(env.tmp / "proj", okf="init-ai-workspace")
    okf = proj / "ai" / "scripts" / "okf"
    before = okf.read_text(encoding="utf-8")

    rc, out = run(capsys, "--project", proj, "--fix-shims")
    assert rc == 0
    assert "-SKILL=\"${OKF_SKILL_DIR:-$HOME/.claude/skills/init-ai-workspace}\"" in out
    assert "+SKILL=\"${OKF_SKILL_DIR:-$HOME/.claude/skills/lk-init-ai-workspace}\"" in out
    assert okf.read_text(encoding="utf-8") == before

    rc, out = run(capsys, "--project", proj, "--fix-shims", "--yes")
    assert rc == 0
    after = okf.read_text(encoding="utf-8")
    assert after == before.replace("skills/init-ai-workspace}", "skills/lk-init-ai-workspace}")

    rc, out = run(capsys, "--project", proj, "--fix-shims", "--yes")
    assert rc == 0 and "nothing to fix" in out
    rc, out = run(capsys, "--project", proj)
    assert lines(out, "PASS", "okf shim")


def test_fix_shims_preserves_crlf_line_endings(env, capsys):
    proj = make_project(env.tmp / "proj", okf=None)
    okf = proj / "ai" / "scripts" / "okf"
    okf.parent.mkdir(parents=True, exist_ok=True)
    okf.write_bytes(shim("init-ai-workspace").replace("\n", "\r\n").encode("utf-8"))
    rc, out = run(capsys, "--project", proj, "--fix-shims", "--yes")
    assert rc == 0
    data = okf.read_bytes()
    assert b"skills/lk-init-ai-workspace}" in data
    assert data.count(b"\r\n") == data.count(b"\n")
