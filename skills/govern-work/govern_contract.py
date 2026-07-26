#!/usr/bin/env python3
"""govern-work CONTRACT RUNNER (Wave 3) -- mint / verify / land / abort, over git worktrees.

Lives beside govern.py in the same skill dir and imports it directly (`import govern as gov`) --
both files ship together as one skill install, so this is NOT the cross-skill coupling govern.py's
own module docstring avoids with init-ai-workspace/okf_normalize.py. Reuses gov's markdown-section
parsing (`_headings`/`_section_lines`), path-reference regexes (`_BACKTICK_PATH`/`_MD_LINK`), note
writer (`write_note`), config reader (`read_conf`/`find_config`), and `lint_spec()` rather than
re-implementing any of it -- see the Decisions section of this wave's report for why.

Dispatch: `govern.py`'s own `main()` forwards to this module's `main()` whenever argv[0] is one of
mint/verify/land/abort (flat-flag style everywhere else, subcommand style here, because these verbs
take genuinely different positional/option shapes -- see report Decisions).

  gov mint <spec.md> [--id ID] [--base-branch BRANCH] [--worktree-dir DIR]
  gov verify --id ID
  gov land --id ID [--allow-enforcement-edit] [--accept-next-agent-item "<text>" ...]
  gov abort --id ID [--underspecified --reason "<gap>" [--reason "<gap>" ...]]

Contract state: one JSON file per contract at `ai/contracts/<id>.json` in the MAIN repo (never the
worktree) -- gitignored (`ai/contracts/*.json`, appended by `mint`), because it is operational
bookkeeping (worktree path, timestamps, override flags) that would otherwise pollute every commit on
the base branch with churn for contracts that never land. The builder's REPORT is a normal tracked
file at the path the spec itself declares (via `Report:` / `## Report`) -- it becomes durable
automatically as a side effect of the ff-only merge at `land`, no separate "persist" step needed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import govern as gov

CONTRACT_VERBS = {"mint", "verify", "land", "abort"}

CONTRACTS_DIRNAME = "contracts"          # ai/contracts/
GITIGNORE_PATTERN = "ai/contracts/*.json"

CORE_DENY = ("ai/scripts/gov", "ai/scripts/okf")  # kept in sync BY HAND with hooks/pre-commit


# --------------------------------------------------------------------------- small utils

def _safe_stdio():
    gov._safe_stdio()


def _tmpbase() -> str:
    """Same TMPDIR/TMP/TEMP/tmp precedence as hooks/pre-commit -- see that file's own comment."""
    return os.environ.get("TMPDIR") or os.environ.get("TMP") or os.environ.get("TEMP") or "/tmp"


def _sanitize(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", text)


def marker_path_for(toplevel: str) -> Path:
    """Identical formula to hooks/pre-commit's own (see that file + wave2b-hooks-report.md,
    Decision #1 -- this is the binding contract this wave must honor)."""
    return Path(_tmpbase()) / "govern-work" / f"contract-{_sanitize(toplevel)}.deny"


def write_marker(toplevel: str, extra_paths: list[str] | None = None) -> Path:
    m = marker_path_for(toplevel)
    m.parent.mkdir(parents=True, exist_ok=True)
    body = ""
    if extra_paths:
        body = "\n".join(extra_paths) + "\n"
    m.write_text(body, encoding="utf-8")
    return m


def remove_marker(toplevel: str) -> None:
    m = marker_path_for(toplevel)
    try:
        m.unlink()
    except FileNotFoundError:
        pass


def run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and r.returncode != 0:
        raise GitError(f"git {' '.join(args)} (cwd={cwd}) failed:\n{r.stdout}\n{r.stderr}")
    return r


class GitError(RuntimeError):
    pass


class Refused(RuntimeError):
    """Raised by any gate. Message already names the fix (R15) -- printed verbatim to stderr."""


# --------------------------------------------------------------------------- contract state

def contracts_dir(root: Path) -> Path:
    return root / "ai" / CONTRACTS_DIRNAME


def contract_json_path(root: Path, contract_id: str) -> Path:
    return contracts_dir(root) / f"{contract_id}.json"


def load_contract(root: Path, contract_id: str) -> dict:
    p = contract_json_path(root, contract_id)
    if not p.is_file():
        raise Refused(
            f"no such contract: {contract_id} -- no state file at {p}. Run `gov mint <spec>` "
            "first, or check the id (list ai/contracts/*.json for live ones)."
        )
    return json.loads(p.read_text(encoding="utf-8"))


def save_contract(root: Path, contract_id: str, data: dict) -> Path:
    p = contract_json_path(root, contract_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return p


def list_live_contracts(root: Path, exclude_id: str | None = None) -> list[tuple[str, dict]]:
    out = []
    d = contracts_dir(root)
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.json")):
        cid = p.stem
        if cid == exclude_id:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("status") == "active":
            out.append((cid, data))
    return out


def ensure_gitignored(root: Path) -> bool:
    """Idempotently append the contract-state glob to .gitignore. Never touches anything else in
    the file (append-only, marker-free-but-content-checked -- same non-destructive spirit as
    init-ai-workspace's marker convention, just keyed on the literal line instead of an HTML
    comment since .gitignore has no comment-marker convention of its own worth inventing).
    Returns True iff it wrote something -- `mint` immediately commits that change itself (see
    caller), so its own bookkeeping never leaves the MAIN repo's tree dirty for `land`'s
    clean-tree check, which would otherwise trip on every first-ever mint in a repo."""
    gi = root / ".gitignore"
    existing = gi.read_text(encoding="utf-8") if gi.is_file() else ""
    if GITIGNORE_PATTERN in existing.splitlines():
        return False
    sep = "" if (not existing or existing.endswith("\n")) else "\n"
    with gi.open("a", encoding="utf-8") as f:
        f.write(f"{sep}{GITIGNORE_PATTERN}\n")
    return True


# --------------------------------------------------------------------------- spec parsing (reuse gov)

def extract_declared_paths(spec_text: str) -> set[str]:
    """Repo-relative paths the spec references -- same extraction lint_spec's R14 path-existence
    check already uses (gov._BACKTICK_PATH / gov._MD_LINK), reused here as the definition of
    "declared paths" for the mint-time overlap warning. Not a new spec syntax to learn."""
    out: set[str] = set()
    for m in gov._BACKTICK_PATH.finditer(spec_text):
        out.add(m.group(1).split("#", 1)[0].strip())
    for m in gov._MD_LINK.finditer(spec_text):
        target = m.group(1)
        if "://" in target or not ("/" in target or target.endswith(".md")):
            continue
        out.add(target.split("#", 1)[0].strip())
    return {p for p in out if p and not p.startswith(("http:", "https:"))}


def extract_report_path(spec_text: str) -> str | None:
    lines = spec_text.splitlines()
    for line in lines:
        m = gov._REPORT_LINE.match(line)
        if m:
            return m.group(1).strip("`")
    headings = gov._headings(lines)
    section = gov._section_lines(lines, headings, "Report")
    if section is not None:
        for line in section:
            bm = gov._BULLET.match(line) or gov._BACKTICK_PATH.search(line)
            if bm:
                candidate = bm.group(1) if hasattr(bm, "group") else None
                if candidate:
                    inner = gov._BACKTICK_PATH.search(candidate)
                    return (inner.group(1) if inner else candidate).strip()
            stripped = line.strip("` \t")
            if stripped and ("/" in stripped) and len(stripped.split()) == 1:
                return stripped
    return None


def parse_verify_expectation(claude_md_text: str) -> str | None:
    """Within the CLAUDE.md `## Verify...` section, an `Expected: <substring>` line (optionally
    `**Expected:**`, optionally followed by an ignored `<!-- band: ... -->` tolerance comment,
    matching the doctrine pack's SS2.6 RRM CLAUDE.md shape). Returns None when no such line exists
    -- `verify` then falls back to exit-code-only, which is a real, documented degrade, not silence
    (see cmd_verify). This convention is layered ON TOP of Wave 1's placeholder-freeness check in
    gov._check_verify_expectation, not a competing second one -- lint-spec doesn't require this
    exact line (only non-placeholder content), `verify` degrades gracefully when it's absent."""
    lines = claude_md_text.splitlines()
    headings = gov._headings(lines)
    verify_heading = next((h for h, _ in headings if "verify" in h.lower()), None)
    if verify_heading is None:
        return None
    section = gov._section_lines(lines, headings, verify_heading) or []
    for line in section:
        m = re.match(r"^\s*\**Expected(?:\s+result)?\**\s*:\s*(.+?)\s*$", line, re.IGNORECASE)
        if m:
            return re.sub(r"\s*<!--.*?-->\s*$", "", m.group(1)).strip()
    return None


# --------------------------------------------------------------------------- rights / onboarding

YOUR_RIGHTS_BLOCK = """\
## Your rights (R10 -- advisory-strength, same as every guard in this system)

1. **A self-contained brief.** Everything you need to start is in this file: the spec verbatim,
   the one verify command, the report path, and this rights block. You should never need context
   from outside this onboarding to begin.
2. **Verify before you are judged.** `verify` is a dry-run gate -- run it as many times as you
   want, at any point. You are never graded against a check you could not first run yourself.
3. **The right to say "underspecified," not fabricate confidence.** If the brief genuinely does
   not give you enough to proceed honestly, `abort --underspecified --reason "<gap>"` is a valid,
   honored OUTCOME -- not a failure. It keeps your branch, files an open question per named gap,
   and is reported as exactly what it is.
4. **The right to challenge, in the ledger, never in the diff.** You may never silently ignore or
   re-argue a standing decision note. You may always file an open question (`gov --open`) that
   cites the decision's note id and states new evidence. That is the whole difference between
   re-adjudication (forbidden) and honest clarification (always allowed).
5. **The right to be heard past your own contract.** Your report's `## For the next agent` section
   is read by the orchestrator at `land`, not discarded. Items it agrees with become durable notes
   in `ai/memory/`; the rest still ships with your persisted report. Abstaining is fine -- write
   `none`.
"""

STANDING_BOILERPLATE = """\
## How this contract works (standing boilerplate, same for every mint)

- **You are isolated in your own worktree and branch.** There is no file whitelist / fence --
  that was tried, made deliverables worse (agents contorted code to stay in-fence), and was
  retired. Touch whatever files the work genuinely needs.
- **A short DENY LIST is the one hard rule.** A handful of enforcement paths -- the gov/okf shims,
  this project's ratchet baseline -- are refused by a pre-commit hook regardless of what you touch
  elsewhere. An agent that can edit the referee that judges it is not enforced. If your work
  genuinely needs one of those paths, say so in your report; editing it needs an explicit re-mint
  with `--allow-enforcement-edit` and the human's loud, recorded go.
- **Quote, don't paraphrase.** If you record a human ruling as a decision note, use their own
  words, dated. A paraphrase invites re-litigation; a direct quote mostly doesn't.
- **This is advisory-strength, not airtight.** Nothing here stops an agent with a shell from
  bypassing a check on purpose. The floor is "mechanical default," not "impossible to route
  around." Work honestly; the tools exist to make the honest path the easy path.
- **`land` refuses without a report containing a `## Decisions` section** (`none` is a completely
  valid answer if you made no judgement calls). This is the ledger gate -- the whole point of this
  system is that the write happens here, once, cheaply, not scattered mid-work.
"""


def render_onboarding(*, contract_id: str, spec_text: str, verify_command: str, report_path: str,
                       base_branch: str, branch: str) -> str:
    return (
        f"# Contract onboarding: {contract_id}\n\n"
        "This file is everything you need. You should not need any other context to start.\n\n"
        "## Your spec (verbatim)\n\n"
        f"{spec_text.rstrip()}\n\n"
        "## Verify\n\n"
        f"Run this from the root of your worktree, exactly:\n\n```\n{verify_command}\n```\n\n"
        "This is the ONE blessed verify command for this project. Run it via `gov verify --id "
        f"{contract_id}` (it runs the same command and parses the same expected result from "
        "CLAUDE.md) as many times as you like -- it is a dry-run, never a grading event.\n\n"
        "## Report\n\n"
        f"Write your completion report to `{report_path}` (relative to this worktree's root) "
        "before running `gov land`. It MUST contain a `## Decisions` section (`none` is a valid "
        "body). It MAY contain an optional `## For the next agent` section.\n\n"
        f"{YOUR_RIGHTS_BLOCK}\n"
        f"{STANDING_BOILERPLATE}\n"
        "## Housekeeping\n\n"
        f"- Contract id: `{contract_id}`\n"
        f"- Branch: `{branch}` (based on `{base_branch}`)\n"
        f"- When done: `gov land --id {contract_id}` from the MAIN repo (not this worktree).\n"
        f"- If you must stop early: `gov abort --id {contract_id}` (or `--underspecified "
        "--reason \"...\"` if the brief itself is the blocker) from the MAIN repo.\n"
    )


# --------------------------------------------------------------------------- verify

def run_verify_command(worktree: Path, command: str) -> subprocess.CompletedProcess:
    return subprocess.run(command, shell=True, cwd=str(worktree), capture_output=True, text=True)


def do_verify(root: Path, worktree: Path, conf: dict[str, str]) -> tuple[bool, str]:
    """Returns (ok, message). Never raises -- verify degrading loudly is the whole feature."""
    command = conf.get("govern_verify_command")
    if not command:
        return False, (
            "gov verify: refused -- no `govern_verify_command` set in ai/okf.conf. Add one "
            "line, e.g. `govern_verify_command = python -m pytest -q`, naming the single "
            "blessed verify command for this project."
        )
    claude_md = worktree / "CLAUDE.md"
    expected = None
    if claude_md.is_file():
        expected = parse_verify_expectation(claude_md.read_text(encoding="utf-8"))
    proc = run_verify_command(worktree, command)
    output = (proc.stdout or "") + (proc.stderr or "")
    lines = [f"$ {command}", output.rstrip(), f"(exit {proc.returncode})"]
    if proc.returncode != 0:
        lines.append(f"VERIFY FAILED -- command exited {proc.returncode}, expected 0.")
        return False, "\n".join(lines)
    if expected is not None and expected not in output:
        lines.append(
            f"VERIFY FAILED -- exit 0, but the expected result from CLAUDE.md's Verify section "
            f"({expected!r}) was not found in the output. Either the command's output changed "
            f"(update CLAUDE.md's `Expected:` line) or the work regressed something."
        )
        return False, "\n".join(lines)
    lines.append(
        "VERIFY OK"
        + ("" if expected is None else f" -- exit 0 and found expected result {expected!r}.")
        + ("" if expected is not None else
           " -- exit 0. (CLAUDE.md's Verify section names no `Expected:` line, so only the exit "
           "code was checked -- add one for a stronger gate.)")
    )
    return True, "\n".join(lines)


def cmd_verify(args) -> int:
    root = gov.find_git_root(Path.cwd())
    if root is None:
        print("gov verify: not inside a git repository.", file=sys.stderr)
        return 2
    contract = load_contract(root, args.id)
    worktree = Path(contract["worktree"])
    if not worktree.is_dir():
        print(f"gov verify: worktree missing on disk: {worktree} -- was the contract already "
              "landed or aborted?", file=sys.stderr)
        return 2
    conf = gov.read_conf(gov.find_config(worktree))
    ok, message = do_verify(root, worktree, conf)
    print(message)
    return 0 if ok else 1


# --------------------------------------------------------------------------- mint

def cmd_mint(args) -> int:
    root = gov.find_git_root(Path.cwd())
    if root is None:
        print("gov mint: not inside a git repository.", file=sys.stderr)
        return 2
    spec_path = Path(args.spec)
    if not spec_path.is_file():
        print(f"gov mint: refused -- no such spec file: {spec_path}", file=sys.stderr)
        return 1

    # ---- R5 sizing + R14 underspecification guards, BEFORE anything exists ----
    lint = gov.lint_spec(spec_path)
    for line in lint.overrides:
        print(line)
    if not lint.ok:
        print(f"gov mint: REFUSED -- {spec_path} fails {len(lint.fatals)} guard(s) (nothing "
              f"was created -- fix the spec and re-run):")
        for msg in lint.fatals:
            print(f"  ! {msg}")
        return 1

    spec_text = spec_path.read_text(encoding="utf-8")
    contract_id = args.id or gov.slugify(spec_path.stem, max_words=6)
    if contract_json_path(root, contract_id).is_file():
        print(f"gov mint: refused -- a contract with id '{contract_id}' already has state at "
              f"{contract_json_path(root, contract_id)}. Pass --id to choose a different one, or "
              f"`gov land`/`gov abort` the existing one first.", file=sys.stderr)
        return 1

    conf = gov.read_conf(gov.find_config(spec_path.parent) or gov.find_config(root))
    if not conf.get("govern_verify_command"):
        print("gov mint: REFUSED -- no `govern_verify_command` set in ai/okf.conf. Add one line, "
              "e.g. `govern_verify_command = python -m pytest -q`, naming the single blessed "
              "verify command this project trusts, before minting any contract.", file=sys.stderr)
        return 1

    report_rel = extract_report_path(spec_text)
    if not report_rel:
        print("gov mint: REFUSED -- could not determine a concrete report path from the spec. "
              "Add a line `Report: <path/to/report.md>` naming exactly where the builder's "
              "completion report will be written.", file=sys.stderr)
        return 1

    base_branch = args.base_branch or conf.get("govern_base_branch") or "main"
    branch = f"contract/{contract_id}"
    worktree_dir_cfg = args.worktree_dir or conf.get("govern_worktree_dir")
    if worktree_dir_cfg:
        wdir = Path(worktree_dir_cfg)
        wdir = wdir if wdir.is_absolute() else (root / wdir)
    else:
        wdir = root.parent / f"{root.name}-contracts"
    worktree = wdir / contract_id
    if worktree.exists():
        print(f"gov mint: refused -- worktree path already exists: {worktree}. Remove it or pass "
              "--worktree-dir.", file=sys.stderr)
        return 1

    # ---- non-fatal declared-path overlap warning (R3: sequencing signal, never a gate) ----
    declared_paths = extract_declared_paths(spec_text)
    for other_id, other in list_live_contracts(root, exclude_id=contract_id):
        shared = declared_paths & set(other.get("declared_paths", []))
        if shared:
            print(f"gov mint: WARNING -- declared-path overlap with live contract '{other_id}': "
                  f"{sorted(shared)}. Not a refusal (R3 -- the worktree is the isolation "
                  f"boundary); this is a heads-up so you don't dispatch two agents onto the same "
                  f"file at once.")

    trivially_true = (conf.get("govern_verify_trivially_true") or "").strip().lower() in (
        "1", "true", "yes")
    if trivially_true:
        print("=" * 78)
        print("R15 NOTICE: this project's `govern_verify_command` is explicitly configured as")
        print("TRIVIALLY TRUE (govern_verify_trivially_true = true in ai/okf.conf). `land` will")
        print("still enforce the deny-list and the ledger gate (a report with `## Decisions`),")
        print("but a green `verify` here does NOT mean the work is correct -- only that the")
        print("ledger is complete and the enforcement instruments are untouched. Recorded on")
        print(f"this contract's JSON as trivially_true_verify: true.")
        print("=" * 78)

    # ---- create the worktree ----
    try:
        wdir.mkdir(parents=True, exist_ok=True)
        run_git(["worktree", "add", "-b", branch, str(worktree), base_branch], cwd=root)
    except GitError as e:
        print(f"gov mint: git worktree creation failed:\n{e}", file=sys.stderr)
        return 2

    # ---- install the deny-list pre-commit hook (shared across all worktrees of this repo) ----
    hook_note = install_hook(worktree)
    if hook_note:
        print(hook_note)

    # ---- arm the TMPDIR marker for THIS worktree's toplevel ----
    wt_top = run_git(["rev-parse", "--show-toplevel"], cwd=worktree).stdout.strip()
    marker_extra = []
    if args.allow_enforcement_edit:
        marker_extra = []  # allow-enforcement-edit is a land-time opt-in, not a mint-time deny-widen
    write_marker(wt_top, marker_extra)

    if ensure_gitignored(root):
        # Commit mint's own bookkeeping change immediately -- an uncommitted .gitignore edit
        # sitting in the main repo would otherwise trip `land`'s clean-tree check on literally
        # the first mint ever run in a repo, for a change the operator never made themselves.
        run_git(["add", ".gitignore"], cwd=root)
        run_git(["commit", "-q", "-m", "gov mint: ignore ai/contracts/*.json (contract state)"],
                cwd=root, check=False)

    contract = {
        "id": contract_id,
        "spec_path": str(spec_path.resolve().relative_to(root)) if _is_relative_to(spec_path.resolve(), root) else str(spec_path.resolve()),
        "worktree": str(worktree.resolve()),
        "worktree_toplevel": wt_top,
        "branch": branch,
        "base_branch": base_branch,
        "report_path": report_rel,
        "declared_paths": sorted(declared_paths),
        "overrides": lint.overrides,
        "trivially_true_verify": trivially_true,
        "allow_enforcement_edit": bool(args.allow_enforcement_edit),
        "created": gov.now_iso(),
        "status": "active",
        "landed_at": None,
        "aborted_at": None,
        "underspecified_reasons": [],
    }
    save_contract(root, contract_id, contract)

    verify_command = conf["govern_verify_command"]
    onboarding = render_onboarding(
        contract_id=contract_id, spec_text=spec_text, verify_command=verify_command,
        report_path=report_rel, base_branch=base_branch, branch=branch,
    )
    # mint writes this file for the builder to read, not because the operator asked for it -- it
    # must never trip `land`'s clean-worktree check nor land into the merged history itself. Marking
    # it locally-excluded (this worktree's own git exclude file, never committed/shared) means `git
    # status` never sees it as untracked, so a builder who does nothing but the assigned work still
    # lands on a clean first try. See _ignore_onboarding_locally for why this, not .gitignore.
    _ignore_onboarding_locally(worktree)
    (worktree / "CONTRACT-ONBOARDING.md").write_text(onboarding, encoding="utf-8")

    print(f"\nMINTED contract '{contract_id}'")
    print(f"  worktree: {worktree}")
    print(f"  branch:   {branch} (from {base_branch})")
    print(f"  onboarding: {worktree / 'CONTRACT-ONBOARDING.md'}")
    print()
    print(onboarding)
    return 0


def _is_relative_to(p: Path, other: Path) -> bool:
    try:
        p.relative_to(other)
        return True
    except ValueError:
        return False


def _ignore_onboarding_locally(worktree: Path) -> None:
    """Exclude CONTRACT-ONBOARDING.md from `git status` in THIS worktree only, via its own git
    exclude file (`.git/info/exclude`-equivalent for a worktree) -- never a tracked `.gitignore`
    edit, because this file is disposable scaffolding `mint` writes for the builder to read, not
    part of the deliverable. Committing a `.gitignore` rule for it would still leave it eligible to
    land into the merged history if a builder `git add -A`'d; excluding it locally means it simply
    never shows up as a change to commit, on either side of that mistake. Best-effort: a failure
    here should never abort a mint that otherwise succeeded, `land`'s clean-tree check just does
    slightly more work if it's not there.
    """
    try:
        exclude_raw = run_git(["rev-parse", "--git-path", "info/exclude"], cwd=worktree).stdout.strip()
    except GitError:
        return
    exclude_path = Path(exclude_raw)
    if not exclude_path.is_absolute():
        exclude_path = worktree / exclude_path
    line = "/CONTRACT-ONBOARDING.md"
    try:
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude_path.read_text(encoding="utf-8") if exclude_path.is_file() else ""
        if line in existing.splitlines():
            return
        with exclude_path.open("a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(line + "\n")
    except OSError:
        return


def install_hook(worktree: Path) -> str | None:
    src = Path(__file__).resolve().parent / "hooks" / "pre-commit"
    if not src.is_file():
        return ("WARNING: hooks/pre-commit not found next to govern_contract.py -- the deny-list "
                "hook was NOT installed. Enforcement will not run for this contract.")
    hooks_path_raw = run_git(["rev-parse", "--git-path", "hooks"], cwd=worktree).stdout.strip()
    hooks_dir = Path(hooks_path_raw)
    if not hooks_dir.is_absolute():
        hooks_dir = worktree / hooks_dir
    hooks_dir.mkdir(parents=True, exist_ok=True)
    dest = hooks_dir / "pre-commit"
    src_text = src.read_text(encoding="utf-8")
    if dest.is_file():
        existing = dest.read_text(encoding="utf-8", errors="replace")
        if existing == src_text:
            return None  # already installed, identical -- nothing to do (idempotent)
        if "govern-work enforcement-path deny-list guard" not in existing:
            return (f"WARNING: {dest} already exists and is NOT a govern-work hook -- left it "
                     "alone rather than overwrite a hook you may depend on. The deny-list will "
                     "NOT be enforced until you install hooks/pre-commit there yourself.")
    dest.write_text(src_text, encoding="utf-8")
    try:
        st = os.stat(dest)
        os.chmod(dest, st.st_mode | 0o111)
    except OSError:
        pass
    return None


# --------------------------------------------------------------------------- abort

def cmd_abort(args) -> int:
    root = gov.find_git_root(Path.cwd())
    if root is None:
        print("gov abort: not inside a git repository.", file=sys.stderr)
        return 2
    contract = load_contract(root, args.id)
    if contract.get("status") != "active":
        print(f"gov abort: contract '{args.id}' is already {contract.get('status')!r} -- nothing "
              "to abort.", file=sys.stderr)
        return 1

    if args.underspecified:
        reasons = [r.strip() for r in (args.reason or []) if r.strip()]
        if not reasons:
            print("gov abort --underspecified: refused -- pass at least one `--reason \"<gap>\"` "
                  "naming what's missing. Underspecified is a valid outcome, but it still names "
                  "the gap.", file=sys.stderr)
            return 1
        bundle = Path(gov.DEFAULT_BUNDLE)
        bundle = bundle if bundle.is_absolute() else (root / bundle)
        filed = []
        for reason in reasons:
            body = (
                f"Contract `{args.id}` was aborted as UNDERSPECIFIED. This is a valid outcome "
                "(R11), not a failure -- the builder was never required to fabricate confidence "
                "to reach green.\n\n"
                f"**Named gap:** {reason}\n\n"
                f"Spec: {contract.get('spec_path')}\n\n"
                "Close it with:\n"
                f"  gov --rule <this-note-path> --verbatim \"<the human's own words>\"\n"
            )
            path = gov.write_note(
                bundle, type_=gov.OPEN_QUESTION_TYPE, slug=gov.slugify(f"{args.id} {reason}"),
                title=f"[{args.id}] {reason}"[:80], description=reason[:140], body=body,
                source=contract.get("report_path") or gov.DEFAULT_NOTE_SOURCE, status="open",
            )
            filed.append(str(path))
        contract["status"] = "refused-underspecified"
        contract["aborted_at"] = gov.now_iso()
        contract["underspecified_reasons"] = reasons
        contract["underspecified_notes"] = filed
    else:
        contract["status"] = "aborted"
        contract["aborted_at"] = gov.now_iso()

    _teardown_worktree_keep_branch(root, contract)
    save_contract(root, args.id, contract)

    if args.underspecified:
        print(f"ABORTED (refused-underspecified) contract '{args.id}' -- this is a valid "
              "outcome, not a failure.")
        for reason in contract["underspecified_reasons"]:
            print(f"  gap: {reason}")
        for note in contract["underspecified_notes"]:
            print(f"  filed: {note}")
    else:
        print(f"ABORTED contract '{args.id}'. Branch '{contract['branch']}' was KEPT for "
              f"autopsy -- delete it yourself once you're done: git branch -D {contract['branch']}")
    return 0


def _teardown_worktree_keep_branch(root: Path, contract: dict) -> None:
    worktree = Path(contract["worktree"])
    remove_marker(contract.get("worktree_toplevel", str(worktree)))
    if worktree.is_dir():
        r = run_git(["worktree", "remove", str(worktree), "--force"], cwd=root, check=False)
        if r.returncode != 0:
            print(f"gov: warning -- `git worktree remove` failed ({r.stderr.strip()}); "
                  f"the directory {worktree} may need manual cleanup.", file=sys.stderr)


# --------------------------------------------------------------------------- land

def cmd_land(args) -> int:
    root = gov.find_git_root(Path.cwd())
    if root is None:
        print("gov land: not inside a git repository.", file=sys.stderr)
        return 2
    contract = load_contract(root, args.id)
    if contract.get("status") != "active":
        print(f"gov land: refused -- contract '{args.id}' is {contract.get('status')!r}, not "
              "active. Nothing to land.", file=sys.stderr)
        return 1
    worktree = Path(contract["worktree"])
    branch = contract["branch"]
    base_branch = contract["base_branch"]
    if not worktree.is_dir():
        print(f"gov land: refused -- worktree missing on disk: {worktree}.", file=sys.stderr)
        return 1

    # ---- main repo must be ON base_branch with a clean tree (see report Decisions) ----
    main_head = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root).stdout.strip()
    if main_head != base_branch:
        print(f"gov land: refused -- the main repo is on '{main_head}', not this contract's base "
              f"branch '{base_branch}'. Fix: `git checkout {base_branch}` in the main repo (not "
              "the worktree), then re-run `gov land`.", file=sys.stderr)
        return 1
    root_status = run_git(["status", "--porcelain"], cwd=root).stdout.strip()
    if root_status:
        offending = "\n".join(f"    {line}" for line in root_status.splitlines())
        print(f"gov land: refused -- the main repo's working tree at {root} is not clean. Fix: "
              f"commit or stash your changes there before landing a contract. Offending path(s) "
              f"(`git status --porcelain` output):\n{offending}", file=sys.stderr)
        return 1

    # ---- worktree must be clean (report + all work must be committed) ----
    wt_status = run_git(["status", "--porcelain"], cwd=worktree).stdout.strip()
    if wt_status:
        offending = "\n".join(f"    {line}" for line in wt_status.splitlines())
        print(f"gov land: refused -- the contract worktree at {worktree} has uncommitted "
              f"changes. Fix: commit your work (including the report) inside the worktree, then "
              f"re-run `gov land`. Offending path(s) (`git status --porcelain` output, `?? path` = "
              f"untracked, `M path`/`A path` = staged/modified):\n{offending}", file=sys.stderr)
        return 1

    # ---- rebase onto base ----
    r = run_git(["rebase", base_branch], cwd=worktree, check=False)
    if r.returncode != 0:
        run_git(["rebase", "--abort"], cwd=worktree, check=False)
        print(f"gov land: refused -- rebase onto '{base_branch}' failed with conflicts:\n"
              f"{r.stdout}\n{r.stderr}\nFix: resolve the conflicts by hand inside the worktree "
              f"({worktree}), commit, then re-run `gov land`.", file=sys.stderr)
        return 1

    # ---- deny-list diff check (R4 -- the ONLY hard refusal on file content) ----
    conf = gov.read_conf(gov.find_config(worktree))
    baseline_rel = _relpath_str(gov._baseline_path(conf, root), root)
    deny_list = set(CORE_DENY) | {baseline_rel}
    changed = run_git(["diff", "--name-only", f"{base_branch}...HEAD"], cwd=worktree).stdout.splitlines()
    changed = [c.strip() for c in changed if c.strip()]
    allowed_edit = set()
    if contract.get("allow_enforcement_edit") or args.allow_enforcement_edit:
        allowed_edit = deny_list & set(contract.get("declared_paths", []))
    hit = [c for c in changed if c in deny_list and c not in allowed_edit]
    if hit:
        print(f"gov land: REFUSED -- staged changes touch ENFORCEMENT path(s): {sorted(hit)}.\n"
              "The deny-list must not be able to protect itself (R4). Fix: revert the change to "
              "that path, or re-mint with --allow-enforcement-edit AND the literal path in the "
              "spec's declared paths, with the human's explicit, recorded go.", file=sys.stderr)
        return 1
    if allowed_edit:
        print(f"R4 NOTICE: --allow-enforcement-edit is in effect for this contract -- enforcement "
              f"path(s) {sorted(allowed_edit)} were permitted through because they are literally "
              f"declared in the spec. This is a loud, recorded exception, not a silent one.")

    # ---- verify ----
    ok, message = do_verify(root, worktree, conf)
    print(message)
    if not ok:
        print("gov land: refused -- verify did not pass. Fix the work, then re-run `gov land` "
              "(you can re-check with `gov verify` as many times as you like first).",
              file=sys.stderr)
        return 1

    # ---- ledger gate: report must exist and contain a ## Decisions section (R2/§5b) ----
    report_path = worktree / contract["report_path"]
    if not report_path.is_file():
        print(f"gov land: REFUSED -- no report at {report_path} (the path this contract's spec "
              "declared). Fix: write the completion report there (it must contain a "
              "`## Decisions` section; `none` is a valid body), commit it, and re-run `gov land`.",
              file=sys.stderr)
        return 1
    report_text = report_path.read_text(encoding="utf-8")
    report_lines = report_text.splitlines()
    report_headings = gov._headings(report_lines)
    decisions_section = gov._section_lines(report_lines, report_headings, "Decisions")
    if decisions_section is None or not "\n".join(decisions_section).strip():
        print(f"gov land: REFUSED -- {report_path} has no `## Decisions` section (or it's empty). "
              "This IS the ledger gate -- add the section; write `none` if you made no judgement "
              "calls, and re-run `gov land`.", file=sys.stderr)
        return 1

    next_agent_section = gov._section_lines(report_lines, report_headings, "For the next agent")
    if next_agent_section is not None and "\n".join(next_agent_section).strip():
        print("\n" + "=" * 78)
        print("## For the next agent (orchestrator triage -- R13)")
        print("=" * 78)
        print("\n".join(next_agent_section).strip())
        print("=" * 78)
        print("Items above are NOT auto-filed. Re-run with --accept-next-agent-item \"<text>\" "
              "for each one you agree with -- they become ai/memory/ notes. Anything not "
              "accepted still ships inside the persisted report.\n")

    # ---- all green: merge ff-only ----
    run_git(["merge", "--ff-only", branch], cwd=root)

    # ---- file decision notes from the report's own ## Decisions section ----
    decisions_body = "\n".join(decisions_section).strip()
    filed_decisions = []
    # Source cited on notes filed at land: the report's OWN declared path, relative to the repo
    # root -- not a worktree-absolute path. The worktree is gone by the time anyone reads this
    # note (removed a few lines down), but the report itself now lives at this same relative path
    # in the base branch too, since the merge just brought it in.
    note_source = contract["report_path"]
    if decisions_body.lower() not in ("none", "none.", "- none", "* none"):
        bundle = Path(gov.DEFAULT_BUNDLE)
        bundle = bundle if bundle.is_absolute() else (root / bundle)
        for i, item in enumerate(_split_decision_items(decisions_body), 1):
            clean = re.sub(r"^\s*\d+\.\s*", "", item.strip())
            title = clean.splitlines()[0][:80]
            note_body = (
                f"## Decision (contract {args.id}, {gov.today_iso()})\n\n{clean}\n\n"
                "## Why\n\nRecorded automatically from the contract's own completion report at "
                f"land time.\n\n## Status\n\nAccepted (agent-authored; not a human ruling -- see "
                "govern-work docs on why this is `type: pattern`, not `type: decision`).\n\n"
                f"**Verify:** re-read {note_source} (the report this was filed from) at the "
                f"commit this contract landed.\n"
            )
            path = gov.write_note(
                bundle, type_="pattern", slug=gov.slugify(f"{args.id}-{title}"),
                title=title, description=clean[:140], body=note_body,
                source=note_source, status="unverified",
            )
            filed_decisions.append(str(path))

    filed_next_agent = []
    for item_text in (args.accept_next_agent_item or []):
        bundle = Path(gov.DEFAULT_BUNDLE)
        bundle = bundle if bundle.is_absolute() else (root / bundle)
        path = gov.write_note(
            bundle, type_="pattern", slug=gov.slugify(f"{args.id}-next-agent-{item_text}"),
            title=item_text[:80], description=item_text[:140],
            body=(f"Accepted from contract `{args.id}`'s `## For the next agent` section at "
                  f"land time.\n\n{item_text.strip()}\n\n"
                  f"**Verify:** re-read {note_source} (the report this was accepted from).\n"),
            source=note_source, status="unverified",
        )
        filed_next_agent.append(str(path))

    contract["status"] = "landed"
    contract["landed_at"] = gov.now_iso()
    contract["filed_decision_notes"] = filed_decisions
    contract["filed_next_agent_notes"] = filed_next_agent
    save_contract(root, args.id, contract)

    _teardown_worktree_keep_branch(root, contract)
    # land also removes the now-merged branch (unlike abort, which keeps it for autopsy) -- the
    # work is safely in base_branch's history, keeping the branch around is pure clutter.
    run_git(["branch", "-d", branch], cwd=root, check=False)

    print(f"\nLANDED contract '{args.id}' -- merged '{branch}' into '{base_branch}' (ff-only).")
    if filed_decisions:
        print(f"  filed {len(filed_decisions)} decision note(s): {filed_decisions}")
    if filed_next_agent:
        print(f"  filed {len(filed_next_agent)} accepted next-agent note(s): {filed_next_agent}")
    return 0


def _relpath_str(p: Path, root: Path) -> str:
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(p)


def _split_decision_items(body: str) -> list[str]:
    """Split a report's ## Decisions body into per-item chunks: numbered list items first
    (`1. ...`), else blank-line-separated paragraphs, else the whole body as one item."""
    numbered = re.split(r"\n(?=\d+\.\s)", body.strip())
    numbered = [n for n in numbered if n.strip()]
    if len(numbered) > 1:
        return numbered
    paras = [p for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]
    return paras or [body.strip()]


# --------------------------------------------------------------------------- main

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="gov", description="govern-work contract runner")
    sub = ap.add_subparsers(dest="verb", required=True)

    p_mint = sub.add_parser("mint", help="mint a contract from a spec, over a git worktree")
    p_mint.add_argument("spec", help="path to the spec markdown file")
    p_mint.add_argument("--id", help="contract id (default: slug of the spec filename)")
    p_mint.add_argument("--base-branch", help="branch to base the contract on (default: main, "
                         "or govern_base_branch in ai/okf.conf)")
    p_mint.add_argument("--worktree-dir", help="parent dir for the worktree (default: "
                         "govern_worktree_dir in ai/okf.conf, or ../<repo>-contracts)")
    p_mint.add_argument("--allow-enforcement-edit", action="store_true",
                         help="R4 opt-out, recorded loudly on the contract; still requires the "
                              "path to be literally declared in the spec at land time")
    p_mint.set_defaults(func=cmd_mint)

    p_verify = sub.add_parser("verify", help="run the one blessed verify command (dry-run gate)")
    p_verify.add_argument("--id", required=True)
    p_verify.set_defaults(func=cmd_verify)

    p_land = sub.add_parser("land", help="rebase, deny-check, verify, ledger-gate, merge ff-only")
    p_land.add_argument("--id", required=True)
    p_land.add_argument("--allow-enforcement-edit", action="store_true")
    p_land.add_argument("--accept-next-agent-item", action="append", metavar="TEXT",
                         help="file this text as an ai/memory/ note (repeatable); the "
                              "orchestrator's triage of the report's optional "
                              "'## For the next agent' section")
    p_land.set_defaults(func=cmd_land)

    p_abort = sub.add_parser("abort", help="remove the worktree, keep the branch for autopsy")
    p_abort.add_argument("--id", required=True)
    p_abort.add_argument("--underspecified", action="store_true",
                          help="R11 refusal path: valid outcome, not a failure")
    p_abort.add_argument("--reason", action="append", metavar="TEXT",
                          help="one named gap (repeatable); required with --underspecified")
    p_abort.set_defaults(func=cmd_abort)

    return ap


def main(argv: list[str] | None = None) -> int:
    _safe_stdio()
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except Refused as e:
        print(str(e), file=sys.stderr)
        return 1
    except GitError as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
