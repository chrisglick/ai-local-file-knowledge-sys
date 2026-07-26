"""Tests for govern-work's CONTRACT RUNNER (Wave 3): mint / verify / land / abort.

Real git repos in tmp_path (git worktrees are real filesystem/git operations -- no point faking
them). Calls `govern_contract.main([...])` in-process (via `monkeypatch.chdir`, since the module
resolves the repo root from `Path.cwd()`) rather than subprocess, matching test_govern.py's
in-process convention; git itself is still invoked as a real subprocess inside the module (every
internal call passes an explicit `cwd=`, so chdir is only needed for the module's own
`Path.cwd()` root-resolution calls). `python -m pytest -q` from this directory runs it.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import govern as gov
import govern_contract as gc

CLAUDE_MD_OK = """\
# CLAUDE.md

## Verify

Run:
```
python -c "print('hello world')"
```
Expected: hello world
"""

CLAUDE_MD_PLACEHOLDER = """\
# CLAUDE.md

## Verify

TODO: fill this in later.
"""

OKF_CONF_OK = "archive = local\ngovern_verify_command = python -c \"print('hello world')\"\n"

SPEC_OK = """\
## Goal

Add a hello file.

## Done when

- `hello.txt` exists with content "hi"

## Deliverables

- hello.txt

Lane: docs

Report: report.md
"""


def _run(cmd, cwd, check=True):
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"{cmd} failed rc={r.returncode}\n{r.stdout}\n{r.stderr}")
    return r


def _write(root: Path, rel: str, content: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _init_repo(tmp_path: Path, *, claude_md=CLAUDE_MD_OK, okf_conf=OKF_CONF_OK) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-q", "-b", "master"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "config", "user.name", "Test"], cwd=repo)
    _write(repo, "CLAUDE.md", claude_md)
    _write(repo, "ai/okf.conf", okf_conf)
    (repo / "ai" / "memory").mkdir(parents=True, exist_ok=True)
    _run(["git", "add", "-A"], cwd=repo)
    _run(["git", "commit", "-q", "-m", "init"], cwd=repo)
    return repo


@pytest.fixture
def repo(tmp_path):
    return _init_repo(tmp_path)


def _mint(repo: Path, monkeypatch, spec_name="spec.md", spec_text=SPEC_OK, extra_args=None):
    _write(repo, spec_name, spec_text)
    _run(["git", "add", "-A"], cwd=repo)
    _run(["git", "commit", "-q", "-m", "add " + spec_name], cwd=repo)
    monkeypatch.chdir(repo)
    args = [spec_name, "--base-branch", "master"] + (extra_args or [])
    rc = gc.main(["mint", *args])
    return rc


def _worktree_for(repo: Path, contract_id: str) -> Path:
    return repo.parent / f"{repo.name}-contracts" / contract_id


def _write_report(worktree: Path, decisions_body: str = "none", extra: str = ""):
    _write(worktree, "report.md", f"# Report\n\n## Decisions\n\n{decisions_body}\n\n{extra}")


def _commit_worktree_work(worktree: Path, message="do the work"):
    _run(["git", "add", "-A"], cwd=worktree)
    _run(["git", "-c", "user.email=t@e.com", "-c", "user.name=Test", "commit", "-q", "-m", message],
         cwd=worktree)


# ---------------------------------------------------------------------------
# mint: R5/R14 guards fire BEFORE anything exists
# ---------------------------------------------------------------------------


def test_mint_refuses_oversized_spec_two_goal_headings(repo, monkeypatch, capsys):
    bad_spec = SPEC_OK + "\n## Goal\n\nA second goal.\n"
    rc = _mint(repo, monkeypatch, spec_text=bad_spec)
    out = capsys.readouterr()
    assert rc == 1
    assert "REFUSED" in out.out
    assert "Goal" in out.out
    assert not (repo.parent / f"{repo.name}-contracts").exists(), (
        "nothing should be created when the sizing guard fires"
    )


def test_mint_refuses_placeholder_claude_md_and_names_the_fix(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path, claude_md=CLAUDE_MD_PLACEHOLDER)
    rc = _mint(repo, monkeypatch)
    out = capsys.readouterr()
    assert rc == 1
    assert "REFUSED" in out.out
    assert "placeholder" in out.out.lower()
    assert "CLAUDE.md" in out.out
    # the message tells the HUMAN what to write, not just that something failed (R15)
    assert "verify command" in out.out.lower()


def test_mint_refuses_when_no_verify_command_configured(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path, okf_conf="archive = local\n")
    rc = _mint(repo, monkeypatch)
    out = capsys.readouterr()
    assert rc == 1
    assert "govern_verify_command" in out.out + out.err


def test_mint_refuses_spec_with_no_report_path(repo, monkeypatch, capsys):
    spec = SPEC_OK.replace("Report: report.md\n", "")
    rc = _mint(repo, monkeypatch, spec_text=spec)
    out = capsys.readouterr()
    assert rc == 1
    assert "report" in out.out.lower()


# ---------------------------------------------------------------------------
# mint: happy path + overlap warning (non-fatal)
# ---------------------------------------------------------------------------


def test_mint_happy_path_creates_worktree_marker_hook_and_onboarding(repo, monkeypatch, capsys):
    rc = _mint(repo, monkeypatch)
    out = capsys.readouterr()
    assert rc == 0
    assert "MINTED contract 'spec'" in out.out
    assert "Your rights" in out.out
    assert "R10" in out.out

    worktree = _worktree_for(repo, "spec")
    assert worktree.is_dir()
    assert (worktree / "CONTRACT-ONBOARDING.md").is_file()
    onboarding = (worktree / "CONTRACT-ONBOARDING.md").read_text(encoding="utf-8")
    assert "## Your rights" in onboarding
    assert "Add a hello file." in onboarding  # spec verbatim
    assert "python -c" in onboarding  # verify command

    contract_json = repo / "ai" / "contracts" / "spec.json"
    assert contract_json.is_file()
    data = json.loads(contract_json.read_text(encoding="utf-8"))
    assert data["status"] == "active"
    assert data["branch"] == "contract/spec"

    # hook installed into the SHARED hooks dir
    hooks_path = _run(["git", "rev-parse", "--git-path", "hooks"], cwd=worktree).stdout.strip()
    hooks_dir = Path(hooks_path)
    hooks_dir = hooks_dir if hooks_dir.is_absolute() else (worktree / hooks_dir)
    installed = (hooks_dir / "pre-commit").read_text(encoding="utf-8")
    assert "govern-work enforcement-path deny-list guard" in installed

    # marker armed for the WORKTREE's own toplevel
    wt_top = _run(["git", "rev-parse", "--show-toplevel"], cwd=worktree).stdout.strip()
    assert gc.marker_path_for(wt_top).is_file()
    gc.remove_marker(wt_top)

    # mint's own .gitignore bookkeeping is committed -- main repo tree is clean afterward
    status = _run(["git", "status", "--porcelain"], cwd=repo).stdout
    assert status.strip() == ""
    assert "ai/contracts/*.json" in (repo / ".gitignore").read_text(encoding="utf-8")


def test_mint_overlap_warning_is_non_fatal_and_names_the_other_contract(repo, monkeypatch, capsys):
    # gov._BACKTICK_PATH (reused for declared-path extraction) only matches backtick spans
    # containing a `/`, and R14 requires any such path to exist on disk -- so the shared path
    # under test needs a directory segment and needs to be real.
    _write(repo, "docs/shared.md", "shared\n")
    _run(["git", "add", "-A"], cwd=repo)
    _run(["git", "commit", "-q", "-m", "add shared doc"], cwd=repo)

    spec_with_shared_path = SPEC_OK.replace(
        "- hello.txt", "- hello.txt\n- `docs/shared.md`"
    )
    rc_a = _mint(repo, monkeypatch, spec_name="a.md", spec_text=spec_with_shared_path)
    assert rc_a == 0
    capsys.readouterr()

    spec_b = spec_with_shared_path.replace("Report: report.md", "Report: report-b.md")
    rc_b = _mint(repo, monkeypatch, spec_name="b.md", spec_text=spec_b, extra_args=["--id", "b"])
    out = capsys.readouterr()
    assert rc_b == 0, out.out  # non-fatal: mint still succeeds
    assert "WARNING" in out.out
    assert "overlap" in out.out.lower()
    assert "a" in out.out  # names the other live contract's id
    assert "docs/shared.md" in out.out  # names the exact shared path


# ---------------------------------------------------------------------------
# verify: dry-run gate, parses expectation live from CLAUDE.md
# ---------------------------------------------------------------------------


def test_verify_passes_when_command_exits_zero_and_output_matches(repo, monkeypatch, capsys):
    _mint(repo, monkeypatch)
    capsys.readouterr()
    monkeypatch.chdir(repo)
    rc = gc.main(["verify", "--id", "spec"])
    out = capsys.readouterr()
    assert rc == 0
    assert "VERIFY OK" in out.out


def test_verify_fails_when_expected_result_not_found(tmp_path, monkeypatch, capsys):
    repo = _init_repo(
        tmp_path,
        okf_conf="archive = local\ngovern_verify_command = python -c \"print('bye')\"\n",
    )
    _mint(repo, monkeypatch)
    capsys.readouterr()
    monkeypatch.chdir(repo)
    rc = gc.main(["verify", "--id", "spec"])
    out = capsys.readouterr()
    assert rc == 1
    assert "VERIFY FAILED" in out.out


# ---------------------------------------------------------------------------
# land: acceptance #4 -- refuses a report with no ## Decisions, accepts `none`
# ---------------------------------------------------------------------------


def test_land_refuses_report_with_no_decisions_section(repo, monkeypatch, capsys):
    _mint(repo, monkeypatch)
    capsys.readouterr()
    worktree = _worktree_for(repo, "spec")
    _write(worktree, "hello.txt", "hi")
    _write(worktree, "report.md", "# Report\n\nI did the thing. No decisions section at all.\n")
    _commit_worktree_work(worktree)

    monkeypatch.chdir(repo)
    rc = gc.main(["land", "--id", "spec"])
    out = capsys.readouterr()
    assert rc == 1
    assert "REFUSED" in out.err or "REFUSED" in out.out
    assert "## Decisions" in out.err or "## Decisions" in out.out
    # contract must still be active -- refused, not silently landed
    data = json.loads((repo / "ai" / "contracts" / "spec.json").read_text(encoding="utf-8"))
    assert data["status"] == "active"
    gc.remove_marker(data["worktree_toplevel"])


def test_land_accepts_explicit_none_decisions(repo, monkeypatch, capsys):
    _mint(repo, monkeypatch)
    capsys.readouterr()
    worktree = _worktree_for(repo, "spec")
    _write(worktree, "hello.txt", "hi")
    _write_report(worktree, decisions_body="none")
    _commit_worktree_work(worktree)

    monkeypatch.chdir(repo)
    rc = gc.main(["land", "--id", "spec"])
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err
    assert "LANDED" in out.out
    data = json.loads((repo / "ai" / "contracts" / "spec.json").read_text(encoding="utf-8"))
    assert data["status"] == "landed"
    # explicit "none" must NOT file a decision note
    assert data["filed_decision_notes"] == []


def test_land_ignores_mints_own_onboarding_file_left_uncommitted(repo, monkeypatch, capsys):
    """Regression for fix-wave gap 3: `mint` itself writes an untracked CONTRACT-ONBOARDING.md into
    the worktree. Before the fix, a builder who committed everything THEY touched but never
    committed that file (never asked to -- nothing tells them to) got refused by `land`'s
    clean-worktree check with a generic message that didn't name the file. `mint` must now exclude
    it locally so a builder doing exactly the assigned work lands clean on the first try."""
    _mint(repo, monkeypatch)
    capsys.readouterr()
    worktree = _worktree_for(repo, "spec")
    assert (worktree / "CONTRACT-ONBOARDING.md").is_file()
    # sanity: mint's own file is untracked-but-excluded, not merely absent from git status by luck
    status_before = _run(["git", "status", "--porcelain"], cwd=worktree).stdout
    assert "CONTRACT-ONBOARDING.md" not in status_before

    _write(worktree, "hello.txt", "hi")
    _write_report(worktree, decisions_body="none")
    _commit_worktree_work(worktree)  # deliberately does NOT touch CONTRACT-ONBOARDING.md

    monkeypatch.chdir(repo)
    rc = gc.main(["land", "--id", "spec"])
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err
    assert "LANDED" in out.out
    # the onboarding scratch file never lands in the merged history
    landed_files = _run(["git", "ls-tree", "-r", "--name-only", "master"], cwd=repo).stdout
    assert "CONTRACT-ONBOARDING.md" not in landed_files


def test_land_refusal_for_genuinely_uncommitted_work_names_the_files(repo, monkeypatch, capsys):
    """The clean-worktree refusal must still fire for real uncommitted work, and must name the
    offending path(s) rather than a bare generic message -- so a builder never has to hunt."""
    _mint(repo, monkeypatch)
    capsys.readouterr()
    worktree = _worktree_for(repo, "spec")
    _write(worktree, "hello.txt", "hi")
    _write_report(worktree, decisions_body="none")
    _commit_worktree_work(worktree)
    _write(worktree, "stray-uncommitted.txt", "oops")  # genuine leftover, never committed

    monkeypatch.chdir(repo)
    rc = gc.main(["land", "--id", "spec"])
    out = capsys.readouterr()
    assert rc == 1
    assert "stray-uncommitted.txt" in (out.out + out.err)
    data = json.loads((repo / "ai" / "contracts" / "spec.json").read_text(encoding="utf-8"))
    assert data["status"] == "active"
    gc.remove_marker(data["worktree_toplevel"])


def test_land_refuses_missing_report(repo, monkeypatch, capsys):
    _mint(repo, monkeypatch)
    capsys.readouterr()
    worktree = _worktree_for(repo, "spec")
    _write(worktree, "hello.txt", "hi")
    _commit_worktree_work(worktree)  # no report.md at all

    monkeypatch.chdir(repo)
    rc = gc.main(["land", "--id", "spec"])
    out = capsys.readouterr()
    assert rc == 1
    assert "no report" in (out.out + out.err).lower()
    data = json.loads((repo / "ai" / "contracts" / "spec.json").read_text(encoding="utf-8"))
    gc.remove_marker(data["worktree_toplevel"])


# ---------------------------------------------------------------------------
# land: deny-list diff check (R4)
# ---------------------------------------------------------------------------


def test_land_refuses_when_diff_touches_enforcement_path(repo, monkeypatch, capsys):
    """land's OWN deny-list diff check must catch this independently of the pre-commit hook --
    proven here by bypassing the hook (--no-verify), exactly as an agent with shell access could
    (R8's honesty note: the hook is advisory-strength, not the only line of defense)."""
    _mint(repo, monkeypatch)
    capsys.readouterr()
    worktree = _worktree_for(repo, "spec")
    _write(worktree, "hello.txt", "hi")
    _write(worktree, "ai/scripts/gov", "tampered")
    _write_report(worktree, decisions_body="none")
    _run(["git", "add", "-A"], cwd=worktree)
    _run(
        ["git", "-c", "user.email=t@e.com", "-c", "user.name=Test", "commit", "-q", "--no-verify",
         "-m", "do the work (bypassing the hook on purpose, to test land's own gate)"],
        cwd=worktree,
    )

    monkeypatch.chdir(repo)
    rc = gc.main(["land", "--id", "spec"])
    out = capsys.readouterr()
    combined = out.out + out.err
    assert rc == 1
    assert "ENFORCEMENT" in combined
    assert "ai/scripts/gov" in combined
    data = json.loads((repo / "ai" / "contracts" / "spec.json").read_text(encoding="utf-8"))
    assert data["status"] == "active"
    gc.remove_marker(data["worktree_toplevel"])


def test_land_allows_declared_enforcement_edit_with_mint_time_flag(repo, monkeypatch, capsys):
    """R4's opt-out: --allow-enforcement-edit at mint, PLUS the exact path literally declared in
    the spec, lets that one enforcement path through at land -- loudly, and recorded."""
    _write(repo, "ai/scripts/gov", "#!/bin/sh\necho v1\n")
    _run(["git", "add", "-A"], cwd=repo)
    _run(["git", "commit", "-q", "-m", "seed gov shim"], cwd=repo)

    spec = SPEC_OK.replace("- hello.txt", "- hello.txt\n- `ai/scripts/gov`")
    rc = _mint(repo, monkeypatch, spec_text=spec, extra_args=["--allow-enforcement-edit"])
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err

    data = json.loads((repo / "ai" / "contracts" / "spec.json").read_text(encoding="utf-8"))
    assert data["allow_enforcement_edit"] is True
    assert "ai/scripts/gov" in data["declared_paths"]

    worktree = _worktree_for(repo, "spec")
    _write(worktree, "hello.txt", "hi")
    _write(worktree, "ai/scripts/gov", "#!/bin/sh\necho v2 -- authorized edit\n")
    _write_report(worktree, decisions_body="none")
    _run(["git", "add", "-A"], cwd=worktree)
    _run(
        ["git", "-c", "user.email=t@e.com", "-c", "user.name=Test", "commit", "-q", "--no-verify",
         "-m", "authorized enforcement edit"],
        cwd=worktree,
    )

    monkeypatch.chdir(repo)
    rc = gc.main(["land", "--id", "spec"])
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err
    assert "R4 NOTICE" in out.out  # loud, not silent
    assert (repo / "ai" / "scripts" / "gov").read_text(encoding="utf-8") == (
        "#!/bin/sh\necho v2 -- authorized edit\n"
    )


# ---------------------------------------------------------------------------
# abort: plain, and acceptance #10 (--underspecified)
# ---------------------------------------------------------------------------


def test_abort_plain_keeps_branch_removes_worktree(repo, monkeypatch, capsys):
    _mint(repo, monkeypatch)
    capsys.readouterr()
    monkeypatch.chdir(repo)
    rc = gc.main(["abort", "--id", "spec"])
    out = capsys.readouterr()
    assert rc == 0
    assert "ABORTED" in out.out
    assert not _worktree_for(repo, "spec").exists()
    branches = _run(["git", "branch", "--list", "contract/spec"], cwd=repo).stdout
    assert "contract/spec" in branches
    data = json.loads((repo / "ai" / "contracts" / "spec.json").read_text(encoding="utf-8"))
    assert data["status"] == "aborted"


def test_abort_underspecified_files_open_question_keeps_branch_and_records_outcome(
    repo, monkeypatch, capsys
):
    """Acceptance #10."""
    _mint(repo, monkeypatch)
    capsys.readouterr()
    monkeypatch.chdir(repo)
    rc = gc.main([
        "abort", "--id", "spec", "--underspecified",
        "--reason", "unclear whether hello.txt should be committed with a trailing newline",
    ])
    out = capsys.readouterr()
    assert rc == 0

    # branch kept for autopsy
    branches = _run(["git", "branch", "--list", "contract/spec"], cwd=repo).stdout
    assert "contract/spec" in branches
    assert not _worktree_for(repo, "spec").exists()

    # contract JSON reads refused-underspecified
    data = json.loads((repo / "ai" / "contracts" / "spec.json").read_text(encoding="utf-8"))
    assert data["status"] == "refused-underspecified"
    assert data["underspecified_reasons"] == [
        "unclear whether hello.txt should be committed with a trailing newline"
    ]

    # one open-question note filed
    notes = list((repo / "ai" / "memory").glob("open-question_*.md"))
    assert len(notes) == 1
    body = notes[0].read_text(encoding="utf-8")
    fm, _ = gov.parse_frontmatter(body)
    assert fm["type"] == "open-question"
    assert "trailing newline" in body

    # framed as a valid outcome, not a failure
    assert "valid" in out.out.lower()
    assert "not a failure" in out.out.lower() or "not a failure" in body.lower()


def test_abort_underspecified_requires_a_reason(repo, monkeypatch, capsys):
    _mint(repo, monkeypatch)
    capsys.readouterr()
    monkeypatch.chdir(repo)
    rc = gc.main(["abort", "--id", "spec", "--underspecified"])
    out = capsys.readouterr()
    assert rc == 1
    assert "reason" in (out.out + out.err).lower()
    data = json.loads((repo / "ai" / "contracts" / "spec.json").read_text(encoding="utf-8"))
    assert data["status"] == "active"  # refused, unchanged
    gc.remove_marker(data["worktree_toplevel"])


# ---------------------------------------------------------------------------
# full happy path: mint -> work -> verify -> land
# ---------------------------------------------------------------------------


def test_full_happy_path_mint_work_verify_land(repo, monkeypatch, capsys):
    rc = _mint(repo, monkeypatch)
    assert rc == 0
    capsys.readouterr()

    worktree = _worktree_for(repo, "spec")
    _write(worktree, "hello.txt", "hi")
    _write(
        worktree, "report.md",
        "# Report\n\n## Decisions\n\n1. Wrote hello.txt with content \"hi\" per spec.\n\n"
        "## For the next agent\n\nnone\n",
    )
    _commit_worktree_work(worktree)

    monkeypatch.chdir(repo)
    rc = gc.main(["verify", "--id", "spec"])
    out = capsys.readouterr()
    assert rc == 0
    assert "VERIFY OK" in out.out

    rc = gc.main(["land", "--id", "spec"])
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err
    assert "LANDED" in out.out

    # merged into base branch
    assert (repo / "hello.txt").read_text(encoding="utf-8") == "hi"
    assert (repo / "report.md").is_file()

    # contract JSON updated
    data = json.loads((repo / "ai" / "contracts" / "spec.json").read_text(encoding="utf-8"))
    assert data["status"] == "landed"
    assert len(data["filed_decision_notes"]) == 1

    # decision note filed into ai/memory, type: pattern (not type: decision -- see Decisions)
    notes = list((repo / "ai" / "memory").glob("pattern_*.md"))
    assert len(notes) == 1

    # worktree AND branch both gone (land removes the branch; abort does not)
    assert not worktree.exists()
    branches = _run(["git", "branch", "--list", "contract/spec"], cwd=repo).stdout
    assert "contract/spec" not in branches

    # okf --check still passes on the landed repo (acceptance #7's spirit, scoped to this wave)
    okf_path = (
        Path(__file__).parent.parent / "init-ai-workspace" / "okf_normalize.py"
    )
    if okf_path.is_file():
        import sys as _sys
        r = subprocess.run(
            [_sys.executable, str(okf_path), "ai/memory", "--check"],
            cwd=str(repo), capture_output=True, text=True,
        )
        # pattern-type notes are in TYPE_ENUM and this wave writes clean frontmatter -- expect a
        # clean pass; if not, surface the real output rather than silently ignoring it.
        assert r.returncode == 0, r.stdout + r.stderr
