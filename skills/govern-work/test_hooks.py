"""Tests for govern-work's git hooks: hooks/pre-commit and hooks/stop-gate.sh.

Exercises the hooks via subprocess against throwaway git repos in tmp_path, using git bash
`sh`/`bash` (available on this Windows machine, per the build brief). Mirrors
test_govern.py / test_okf_normalize.py's naming convention (test_<behavior_described>) and is
run the same way: `python -m pytest -q` from this directory.

Covers, at minimum, from the brief's acceptance list:
  #5 the pre-commit hook blocks a staged edit to ai/scripts/gov inside a contract worktree,
     and is silent on a branch/worktree that is not under contract.
  #6 the Stop hook exits 0 cleanly when python is absent (simulated via PATH manipulation).
plus the exact-match property (ai/scripts/gov2, ai/scripts/gov/sub are NOT blocked).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).parent / "hooks"
PRE_COMMIT = HOOKS_DIR / "pre-commit"
STOP_GATE = HOOKS_DIR / "stop-gate.sh"
GOV_SHIM = Path(__file__).parent / "gov.shim.sh"

BASH = shutil.which("bash")


def _skip_if_no_bash():
    if BASH is None:
        pytest.skip("bash not found on PATH -- required to exercise sh hooks")


# ---------------------------------------------------------------------------
# git repo helpers
# ---------------------------------------------------------------------------


def _run(cmd, cwd, env=None, check=True):
    r = subprocess.run(
        cmd, cwd=str(cwd), env=env, capture_output=True, text=True, shell=False
    )
    if check and r.returncode != 0:
        raise AssertionError(
            f"command {cmd} failed rc={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}"
        )
    return r


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-q"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "config", "user.name", "Test"], cwd=repo)
    return repo


def _install_pre_commit_hook(repo: Path):
    hooks_dir = repo / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    dest = hooks_dir / "pre-commit"
    dest.write_bytes(PRE_COMMIT.read_bytes())
    st = os.stat(dest)
    os.chmod(dest, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return dest


def _toplevel(repo: Path) -> str:
    r = _run(["git", "rev-parse", "--show-toplevel"], cwd=repo)
    return r.stdout.strip()


def _marker_path_for(repo: Path) -> str:
    """Compute the exact TMPDIR marker path the hook itself would compute, by running the
    identical shell expression through bash -- avoids reimplementing (and potentially
    mis-porting) the sed/parameter-expansion logic in Python."""
    top = _toplevel(repo)
    script = (
        'top="$1"; '
        'tmpbase="${TMPDIR:-${TMP:-${TEMP:-/tmp}}}"; '
        'sanitized=$(printf %s "$top" | sed "s/[^A-Za-z0-9]/_/g"); '
        'printf "%s/govern-work/contract-%s.deny" "$tmpbase" "$sanitized"'
    )
    r = _run([BASH, "-c", script, "_", top], cwd=repo)
    return r.stdout.strip()


def _touch_marker(repo: Path, extra_lines: str = "") -> str:
    """Simulate `gov mint` having armed this worktree as a contract: create the TMPDIR marker
    file. Returns the marker path."""
    marker = _marker_path_for(repo)
    script = 'mkdir -p "$(dirname "$1")" && printf %s "$2" > "$1"'
    _run([BASH, "-c", script, "_", marker, extra_lines], cwd=repo)
    return marker


def _remove_marker(marker: str):
    if BASH is None:
        return
    subprocess.run([BASH, "-c", 'rm -f "$1"', "_", marker], capture_output=True, text=True)


def _write(repo: Path, rel: str, content: str):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _git_add_commit(repo: Path, message: str, check=True):
    _run(["git", "add", "-A"], cwd=repo)
    return _run(["git", "commit", "-m", message], cwd=repo, check=check)


@pytest.fixture
def repo(tmp_path):
    r = _init_repo(tmp_path)
    yield r


# ---------------------------------------------------------------------------
# pre-commit: contract-worktree detection + deny list
# ---------------------------------------------------------------------------


def test_pre_commit_silent_without_marker_edits_enforcement_path_freely(repo):
    """Not a contract worktree (no marker) -> the hook must stay completely silent, even on a
    staged edit to an enforcement path. This is acceptance #5's second half."""
    _skip_if_no_bash()
    _install_pre_commit_hook(repo)
    _write(repo, "ai/scripts/gov", "#!/bin/sh\necho v1\n")
    r = _git_add_commit(repo, "add gov shim", check=False)
    assert r.returncode == 0, r.stderr

    _write(repo, "ai/scripts/gov", "#!/bin/sh\necho v2\n")
    r = _git_add_commit(repo, "edit gov shim, no marker present", check=False)
    assert r.returncode == 0, f"hook must be inert without a contract marker: {r.stderr}"
    assert "BLOCKED" not in r.stderr


def test_pre_commit_blocks_staged_edit_to_gov_in_contract_worktree(repo):
    """Acceptance #5, first half: the hook blocks a staged edit to ai/scripts/gov once this
    worktree is armed as a contract (TMPDIR marker present)."""
    _skip_if_no_bash()
    _install_pre_commit_hook(repo)
    _write(repo, "ai/scripts/gov", "#!/bin/sh\necho v1\n")
    _git_add_commit(repo, "add gov shim")

    marker = _touch_marker(repo)
    try:
        _write(repo, "ai/scripts/gov", "#!/bin/sh\necho v2 -- tampered\n")
        r = _git_add_commit(repo, "edit gov shim under contract", check=False)
        assert r.returncode != 0, "commit touching ai/scripts/gov must be refused"
        assert "BLOCKED" in r.stderr
        assert "ai/scripts/gov" in r.stderr
        assert "REFUSED" in r.stderr
        # refusal names the fix (R15)
        assert "git restore --staged" in r.stderr
    finally:
        _remove_marker(marker)


def test_pre_commit_blocks_staged_edit_to_okf_in_contract_worktree(repo):
    _skip_if_no_bash()
    _install_pre_commit_hook(repo)
    _write(repo, "ai/scripts/okf", "#!/bin/sh\necho v1\n")
    _git_add_commit(repo, "add okf shim")

    marker = _touch_marker(repo)
    try:
        _write(repo, "ai/scripts/okf", "#!/bin/sh\necho v2\n")
        r = _git_add_commit(repo, "edit okf shim under contract", check=False)
        assert r.returncode != 0
        assert "ai/scripts/okf" in r.stderr
    finally:
        _remove_marker(marker)


def test_pre_commit_blocks_staged_edit_to_ratchet_baseline_default(repo):
    _skip_if_no_bash()
    _install_pre_commit_hook(repo)
    _write(repo, "ai/govern-baseline.json", "{}\n")
    _git_add_commit(repo, "add baseline")

    marker = _touch_marker(repo)
    try:
        _write(repo, "ai/govern-baseline.json", '{"unverified": 999}\n')
        r = _git_add_commit(repo, "edit baseline under contract", check=False)
        assert r.returncode != 0
        assert "ai/govern-baseline.json" in r.stderr
    finally:
        _remove_marker(marker)


def test_pre_commit_honors_configured_ratchet_baseline_path(repo):
    """govern_ratchet_baseline in ai/okf.conf overrides the default baseline path."""
    _skip_if_no_bash()
    _install_pre_commit_hook(repo)
    _write(repo, "ai/okf.conf", "archive = local\ngovern_ratchet_baseline = ai/custom-baseline.json\n")
    _write(repo, "ai/custom-baseline.json", "{}\n")
    _git_add_commit(repo, "add config + custom baseline")

    marker = _touch_marker(repo)
    try:
        _write(repo, "ai/custom-baseline.json", '{"unverified": 5}\n')
        r = _git_add_commit(repo, "edit custom baseline under contract", check=False)
        assert r.returncode != 0
        assert "ai/custom-baseline.json" in r.stderr
    finally:
        _remove_marker(marker)


@pytest.mark.parametrize(
    "path",
    [
        "ai/scripts/gov2",
        "ai/scripts/gov/sub",
        "ai/scripts/govv",
        "notai/scripts/gov",
    ],
)
def test_pre_commit_exact_match_only_does_not_block_near_misses(repo, path):
    """The deny list is exact-match, never a glob/prefix -- editing a path that merely shares a
    prefix or contains the denied string must NOT be blocked."""
    _skip_if_no_bash()
    _install_pre_commit_hook(repo)
    marker = _touch_marker(repo)
    try:
        _write(repo, path, "hello\n")
        r = _git_add_commit(repo, f"add {path}", check=False)
        assert r.returncode == 0, f"{path} must not be treated as a match: {r.stderr}"
        assert "BLOCKED" not in r.stderr
    finally:
        _remove_marker(marker)


def test_pre_commit_allows_unrelated_files_under_contract(repo):
    """Being under contract does not block ordinary work -- only the deny-listed paths."""
    _skip_if_no_bash()
    _install_pre_commit_hook(repo)
    marker = _touch_marker(repo)
    try:
        _write(repo, "src/feature.py", "print('hi')\n")
        r = _git_add_commit(repo, "add feature", check=False)
        assert r.returncode == 0, r.stderr
    finally:
        _remove_marker(marker)


def test_pre_commit_extra_marker_entries_add_to_but_cannot_replace_core_list(repo):
    """Marker file contents can add contract-specific deny paths; core paths remain denied
    regardless of what the marker contains (it cannot be used to shrink the core list)."""
    _skip_if_no_bash()
    _install_pre_commit_hook(repo)
    _write(repo, "ai/scripts/gov", "#!/bin/sh\necho v1\n")
    _write(repo, "docs/special.md", "v1\n")
    _git_add_commit(repo, "seed files")

    marker = _touch_marker(repo, extra_lines="docs/special.md\n# a comment\n")
    try:
        _write(repo, "docs/special.md", "v2\n")
        r = _git_add_commit(repo, "edit contract-specific denied file", check=False)
        assert r.returncode != 0
        assert "docs/special.md" in r.stderr

        _write(repo, "ai/scripts/gov", "#!/bin/sh\necho v2\n")
        r = _git_add_commit(repo, "edit core-denied gov shim too", check=False)
        assert r.returncode != 0
        assert "ai/scripts/gov" in r.stderr
    finally:
        _remove_marker(marker)


def test_pre_commit_allows_merge_commit_with_nothing_staged(repo):
    """Nothing staged (e.g. an empty/merge commit attempt) must not be treated as a match."""
    _skip_if_no_bash()
    _install_pre_commit_hook(repo)
    _write(repo, "README.md", "hi\n")
    _git_add_commit(repo, "seed")
    marker = _touch_marker(repo)
    try:
        r = _run(
            ["git", "commit", "--allow-empty", "-m", "empty commit under contract"],
            cwd=repo,
            check=False,
        )
        assert r.returncode == 0, r.stderr
    finally:
        _remove_marker(marker)


# ---------------------------------------------------------------------------
# stop-gate.sh: graceful degradation
# ---------------------------------------------------------------------------


def _minimal_path_env(extra_dirs=None):
    """Build a PATH containing only what's needed to run bash/git/coreutils -- deliberately
    excluding any directory that resolves python3/python/py, to simulate 'no working python
    found' the same way a stripped-down CI or a python-less machine would look."""
    dirs = []
    for exe in ("bash", "git"):
        p = shutil.which(exe)
        if p:
            d = str(Path(p).parent)
            if d not in dirs:
                dirs.append(d)
    if extra_dirs:
        for d in extra_dirs:
            if d not in dirs:
                dirs.append(d)
    env = {"PATH": os.pathsep.join(dirs)}
    for k in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TMP", "TEMP", "TMPDIR", "HOMEDRIVE", "HOMEPATH", "USERPROFILE"):
        if k in os.environ:
            env[k] = os.environ[k]
    return env


def test_stop_gate_exits_zero_when_not_a_git_repo(tmp_path):
    _skip_if_no_bash()
    bare = tmp_path / "not-a-repo"
    bare.mkdir()
    r = subprocess.run(
        [BASH, str(STOP_GATE)], cwd=str(bare), capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr
    assert "not inside a git repository" in r.stderr


def test_stop_gate_exits_zero_when_no_gov_shim_installed(repo):
    _skip_if_no_bash()
    r = subprocess.run([BASH, str(STOP_GATE)], cwd=str(repo), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "no ai/scripts/gov shim" in r.stderr


def test_stop_gate_exits_zero_when_python_missing_via_path_manipulation(repo):
    """Acceptance #6: the Stop hook must not wedge a session when python is absent. Copies the
    real gov shim into the repo (so stop-gate.sh's own file-existence check passes and it
    actually attempts to run it), then strips PATH down to bash+git only so the shim's own
    python3/python/py probe finds nothing -- exactly the Windows-Store-alias-and-worse case."""
    _skip_if_no_bash()
    assert GOV_SHIM.exists(), "gov.shim.sh must exist (built by Wave 1) to run this test"
    _write(repo, "ai/scripts/gov", GOV_SHIM.read_text(encoding="utf-8"))
    gov_path = repo / "ai" / "scripts" / "gov"
    st = os.stat(gov_path)
    os.chmod(gov_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    env = _minimal_path_env()
    # sanity: confirm python really is unreachable under this stripped PATH before trusting
    # the result below -- otherwise a passing test could just mean python was never invoked.
    probe = subprocess.run(
        [BASH, "-c", 'command -v python3 || command -v python || command -v py'],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
    )
    assert probe.returncode != 0, (
        "test setup invalid: a python interpreter is still reachable under the stripped PATH "
        f"({probe.stdout!r}) -- this test cannot prove anything until PATH truly excludes it"
    )

    r = subprocess.run(
        [BASH, str(STOP_GATE)], cwd=str(repo), env=env, capture_output=True, text=True
    )
    assert r.returncode == 0, f"stop-gate.sh must degrade to exit 0, got {r.returncode}\nstderr={r.stderr}"
    assert "skipping" in r.stderr


def test_stop_gate_propagates_real_gate_exit_code_when_tooling_present(repo):
    """When python IS available and the shim runs, stop-gate.sh must propagate govern.py's
    real exit code rather than always forcing 0 -- otherwise it isn't gating anything. As of
    this wave, govern.py's --gate verb is a stub (Wave 1 report: 'prints "built in a later
    wave", exit 2') -- assert only that SOME code from an actual run is propagated, not 0,
    to avoid coupling this test to a verb this wave does not own."""
    _skip_if_no_bash()
    assert GOV_SHIM.exists()
    _write(repo, "ai/scripts/gov", GOV_SHIM.read_text(encoding="utf-8"))
    gov_path = repo / "ai" / "scripts" / "gov"
    st = os.stat(gov_path)
    os.chmod(gov_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    env = dict(os.environ)
    env["GOV_SKILL_DIR"] = str(Path(__file__).parent)

    r = subprocess.run(
        [BASH, str(STOP_GATE)], cwd=str(repo), env=env, capture_output=True, text=True
    )
    # Whatever govern.py --gate currently returns (a future wave may change this), stop-gate
    # must not silently coerce a real run's result to 0 -- unless the real result already IS 0.
    direct = subprocess.run(
        [BASH, str(gov_path), "--gate"], cwd=str(repo), env=env, capture_output=True, text=True
    )
    assert r.returncode == direct.returncode, (
        f"stop-gate.sh must propagate the real gov --gate exit code ({direct.returncode}), "
        f"got {r.returncode}"
    )
