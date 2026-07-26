"""Tests for govern.py. Run: cd skills/govern-work && python -m pytest -q  (deps: pytest, pyyaml).

Conventions mirror test_okf_normalize.py: import the module directly (no subprocess shelling),
call functions / main([...]) in-process, assert on both return codes and on-disk artifacts in a
tmp_path fixture, descriptive full-sentence test names grouped under `# ---- <area> ----` banners.
"""
import json
from pathlib import Path

import govern as gov

TODAY = "2026-07-25"


def _init_project(root: Path, *, with_claude_md: bool = True, verify_section: str = "    pytest -q\n"):
    """Minimal scaffold: a fake git repo with CLAUDE.md + ai/memory + ai/scripts/gov (the shim's
    own target, needed as the default provenance `source` for notes gov writes)."""
    (root / ".git").mkdir(parents=True, exist_ok=True)
    (root / "ai" / "memory").mkdir(parents=True, exist_ok=True)
    (root / "ai" / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "ai" / "scripts" / "gov").write_text("# shim placeholder\n", encoding="utf-8")
    if with_claude_md:
        (root / "CLAUDE.md").write_text(f"# Project\n\n## Verify\n\n{verify_section}\n", encoding="utf-8")
    return root / "ai" / "memory"


# ---- note-writing round trip: --open then --rule ----

def test_open_then_rule_round_trip(tmp_path):
    bundle = _init_project(tmp_path)
    rc = gov.main(["--open", "should we use approach A or B?", str(bundle)])
    assert rc == 0
    notes = sorted(bundle.glob("open-question_*.md"))
    assert len(notes) == 1
    fm, body = gov.parse_frontmatter(notes[0].read_text(encoding="utf-8"))
    assert fm["type"] == "open-question"
    assert fm["status"] == "open"
    assert fm["source"] == gov.DEFAULT_NOTE_SOURCE

    rc = gov.main(["--rule", str(notes[0]), "--verbatim", '"go with approach A, it\'s simpler"'])
    assert rc == 0
    decisions = sorted(bundle.glob("decision_*.md"))
    assert len(decisions) == 1
    dfm, dbody = gov.parse_frontmatter(decisions[0].read_text(encoding="utf-8"))
    assert dfm["type"] == "decision"
    assert dfm["status"] == "unverified"  # tool-written; status: verified is human-promotion-only
    assert "go with approach A" in dbody
    assert f"supersedes {notes[0].name}" in dfm["relations"]
    assert "## Decision (" in dbody and "## Why" in dbody and "## Status" in dbody \
        and "## Supersedes" in dbody
    assert "**Verify:**" in dbody


def test_rule_closes_the_superseded_open_question_note_in_place(tmp_path):
    """Regression for fix-wave gap 5: `--rule` must not leave the open-question note it supersedes
    still reading `status: open` / "nobody has decided this yet" -- that's exactly the "confidently
    wrong, stale note" failure mode the project's own docs call out as the one real net-negative of
    a note-based system. A reader who opens the OLD file directly (not via index.md or the decision
    note) must see it's closed, with a pointer to the ruling that closed it."""
    bundle = _init_project(tmp_path)
    gov.main(["--open", "should we use approach A or B?", str(bundle)])
    open_note = next(bundle.glob("open-question_*.md"))
    pre_fm, pre_body = gov.parse_frontmatter(open_note.read_text(encoding="utf-8"))
    assert pre_fm["status"] == "open"

    rc = gov.main(["--rule", str(open_note), "--verbatim", '"go with approach A, it\'s simpler"'])
    assert rc == 0
    decision = next(bundle.glob("decision_*.md"))

    post_fm, post_body = gov.parse_frontmatter(open_note.read_text(encoding="utf-8"))
    assert post_fm["status"] == "closed"
    assert "CLOSED" in post_body
    assert decision.name in post_body  # names the closing decision note, not just "see elsewhere"
    assert f"relates {decision.name}" in post_fm["relations"]
    assert "**Verify:**" in post_body  # provenance discipline preserved on the rewritten note too
    # the original question text is still readable above the closed marker
    assert "should we use approach A or B?" in post_body


def test_rule_closing_open_question_keeps_okf_check_conformance(tmp_path):
    """The rewritten open-question note (status: closed, `relates <decision>` relation) must not
    itself introduce an okf_normalize.py --check warning/error -- `relates` is deliberately used
    instead of a made-up verb outside RELATION_VERBS, which --check --strict would flag."""
    import sys as _sys
    okf_dir = Path(__file__).resolve().parent.parent / "init-ai-workspace"
    added = str(okf_dir) not in _sys.path
    if added:
        _sys.path.insert(0, str(okf_dir))
    try:
        import okf_normalize as okf
    finally:
        if added:
            _sys.path.remove(str(okf_dir))

    bundle = _init_project(tmp_path)
    gov.main(["--open", "should X use Y or Z?", str(bundle)])
    open_note = next(bundle.glob("open-question_*.md"))
    gov.main(["--rule", str(open_note), "--verbatim", '"use Y, it is simpler"'])

    rc = okf.main([str(bundle), "--check"])
    assert rc == 0


def test_rule_refuses_empty_verbatim(tmp_path):
    bundle = _init_project(tmp_path)
    gov.main(["--open", "pick a color", str(bundle)])
    note = next(bundle.glob("open-question_*.md"))
    rc = gov.main(["--rule", str(note), "--verbatim", ""])
    assert rc == 1
    assert not list(bundle.glob("decision_*.md"))  # nothing written


def test_rule_refuses_paraphrase_without_quotes(tmp_path):
    bundle = _init_project(tmp_path)
    gov.main(["--open", "pick a color", str(bundle)])
    note = next(bundle.glob("open-question_*.md"))
    rc = gov.main(["--rule", str(note), "--verbatim", "it was decided that blue wins"])
    assert rc == 1
    assert not list(bundle.glob("decision_*.md"))


def test_rule_accepts_paraphrase_shaped_text_if_quoted(tmp_path):
    """The heuristic only fires on meta-phrasing WITHOUT any quote marker -- a verbatim quote
    that happens to describe itself ("we decided" inside real quotes) must not be refused."""
    bundle = _init_project(tmp_path)
    gov.main(["--open", "pick a color", str(bundle)])
    note = next(bundle.glob("open-question_*.md"))
    rc = gov.main(["--rule", str(note), "--verbatim", '"we decided blue, and I mean it"'])
    assert rc == 0


def test_rule_refuses_note_that_is_not_open_question_type(tmp_path):
    bundle = _init_project(tmp_path)
    other = bundle / "decision_already-closed.md"
    other.write_text("---\ntype: decision\ntitle: X\n---\n\nbody\n", encoding="utf-8")
    rc = gov.main(["--rule", str(other), "--verbatim", '"whatever"'])
    assert rc == 1


# ---- lint-spec: R5 sizing guards ----

def _spec(root: Path, name: str, text: str) -> Path:
    p = root / name
    p.write_text(text, encoding="utf-8")
    return p


GOOD_SPEC = """Lane: docs

## Goal

Ship the thing.

## Done when

- `python -m pytest -q` passes with 0 failures
- CLAUDE.md mentions the new verify step

Report: ai/reports/thing-report.md
"""


def test_lint_spec_passes_a_well_formed_spec(tmp_path):
    bundle = _init_project(tmp_path)
    spec = _spec(tmp_path, "good.md", GOOD_SPEC)
    result = gov.lint_spec(spec)
    assert result.ok, result.fatals
    rc = gov.main(["--lint-spec", str(spec)])
    assert rc == 0


def test_lint_spec_refuses_two_goal_headings(tmp_path):
    _init_project(tmp_path)
    text = GOOD_SPEC.replace("## Goal\n\nShip the thing.\n",
                              "## Goal\n\nShip the thing.\n\n## Goal\n\nShip another thing.\n")
    spec = _spec(tmp_path, "two-goals.md", text)
    result = gov.lint_spec(spec)
    assert not result.ok
    assert any("2 `## Goal`" in f or "2 `## Goal` headings" in f for f in result.fatals)
    rc = gov.main(["--lint-spec", str(spec)])
    assert rc == 1


def test_lint_spec_refuses_plural_goals_heading(tmp_path):
    _init_project(tmp_path)
    text = GOOD_SPEC.replace("## Goal", "## Goals", 1)
    spec = _spec(tmp_path, "plural.md", text)
    result = gov.lint_spec(spec)
    assert not result.ok
    assert any("plural" in f for f in result.fatals)


def test_lint_spec_refuses_five_deliverables(tmp_path):
    _init_project(tmp_path)
    text = GOOD_SPEC + "\n## Deliverables\n\n- a\n- b\n- c\n- d\n- e\n"
    spec = _spec(tmp_path, "five-deliv.md", text)
    result = gov.lint_spec(spec)
    assert not result.ok
    assert any("Deliverables" in f and "5" in f for f in result.fatals)


def test_lint_spec_allows_four_deliverables(tmp_path):
    _init_project(tmp_path)
    text = GOOD_SPEC + "\n## Deliverables\n\n- a\n- b\n- c\n- d\n"
    spec = _spec(tmp_path, "four-deliv.md", text)
    result = gov.lint_spec(spec)
    assert result.ok, result.fatals


def test_lint_spec_refuses_missing_done_when(tmp_path):
    _init_project(tmp_path)
    text = "Lane: docs\n\n## Goal\n\nX.\n\nReport: r.md\n"
    spec = _spec(tmp_path, "no-done-when.md", text)
    result = gov.lint_spec(spec)
    assert not result.ok
    assert any("Done when" in f for f in result.fatals)


def test_lint_spec_refuses_vague_done_when_bullet(tmp_path):
    _init_project(tmp_path)
    text = GOOD_SPEC.replace(
        "- `python -m pytest -q` passes with 0 failures\n- CLAUDE.md mentions the new verify step\n",
        "- it works\n")
    spec = _spec(tmp_path, "vague.md", text)
    result = gov.lint_spec(spec)
    assert not result.ok
    assert any("checkable" in f for f in result.fatals)


def test_lint_spec_refuses_more_than_one_lane(tmp_path):
    _init_project(tmp_path)
    text = GOOD_SPEC.replace("Lane: docs", "Lane: docs\nLane: shell")
    spec = _spec(tmp_path, "two-lanes.md", text)
    result = gov.lint_spec(spec)
    assert not result.ok
    assert any("multiple lanes" in f for f in result.fatals)


def test_lint_spec_allow_mixed_lane_override_is_loud_and_recorded(tmp_path):
    _init_project(tmp_path)
    text = GOOD_SPEC.replace("Lane: docs", "Lane: docs\nLane: shell") + \
        "\n## Overrides\n\n- AllowMixedLane: both lanes genuinely needed for this migration\n"
    spec = _spec(tmp_path, "override.md", text)
    result = gov.lint_spec(spec)
    assert result.ok, result.fatals
    assert result.overrides and "AllowMixedLane" in result.overrides[0]


def test_lint_spec_refuses_missing_lane(tmp_path):
    _init_project(tmp_path)
    text = GOOD_SPEC.replace("Lane: docs\n\n", "")
    spec = _spec(tmp_path, "no-lane.md", text)
    result = gov.lint_spec(spec)
    assert not result.ok
    assert any("Lane:" in f for f in result.fatals)


# ---- lint-spec: R14 underspecification guards ----

def test_lint_spec_refuses_referenced_path_that_does_not_exist_and_names_it(tmp_path):
    _init_project(tmp_path)
    text = GOOD_SPEC + "\nSee `ai/nonexistent/file.md` for context.\n"
    spec = _spec(tmp_path, "bad-path.md", text)
    result = gov.lint_spec(spec)
    assert not result.ok
    assert any("ai/nonexistent/file.md" in f for f in result.fatals)
    rc = gov.main(["--lint-spec", str(spec)])
    assert rc == 1


def test_lint_spec_refuses_when_no_claude_md(tmp_path):
    root = tmp_path
    (root / ".git").mkdir()
    spec = _spec(root, "no-claude-md.md", GOOD_SPEC)
    result = gov.lint_spec(spec)
    assert not result.ok
    assert any("CLAUDE.md" in f for f in result.fatals)


def test_lint_spec_refuses_placeholder_verify_section(tmp_path):
    _init_project(tmp_path, verify_section="TODO: fill this in\n")
    spec = _spec(tmp_path, "placeholder-verify.md", GOOD_SPEC)
    result = gov.lint_spec(spec)
    assert not result.ok
    assert any("placeholder" in f for f in result.fatals)


def test_lint_spec_passes_real_verify_content_followed_by_closing_structural_comment(tmp_path):
    """Regression for the fix-wave gap 1 bug: `govern-work-claude-md-section.template.md` ships a
    `<!-- /govern-work -->` closing marker with no heading after it, so it always falls INSIDE the
    scanned `## Verify` section. That marker contains `<`, one of the placeholder marker chars --
    before the fix, a real, filled-in verify command could never pass this check on a CLAUDE.md
    scaffolded verbatim from the shipped template, no matter what the operator wrote."""
    verify_section = (
        "Run this from the repo root, exactly:\n\n"
        "```\n"
        "python -m pytest -q\n"
        "```\n\n"
        "Expected: 3 passed\n"
        "<!-- /govern-work -->\n"
    )
    _init_project(tmp_path, verify_section=verify_section)
    spec = _spec(tmp_path, "real-verify.md", GOOD_SPEC)
    result = gov.lint_spec(spec)
    assert result.ok, result.fatals
    rc = gov.main(["--lint-spec", str(spec)])
    assert rc == 0


def test_lint_spec_still_refuses_placeholder_verify_hidden_only_by_html_comments(tmp_path):
    """The comment-stripping fix must not become a bypass: a Verify section that is STILL a
    placeholder (no real command, only instructional comments) must keep refusing."""
    verify_section = (
        "<!-- FILL IN before minting any contract. -->\n\n"
        "Run this from the repo root, exactly:\n\n"
        "```\n"
        "<TODO: the ONE blessed command>\n"
        "```\n\n"
        "Expected: <TODO: the exact text>\n"
        "<!-- /govern-work -->\n"
    )
    _init_project(tmp_path, verify_section=verify_section)
    spec = _spec(tmp_path, "still-placeholder.md", GOOD_SPEC)
    result = gov.lint_spec(spec)
    assert not result.ok
    assert any("placeholder" in f for f in result.fatals)


def test_lint_spec_refuses_template_header_left_in_by_name(tmp_path):
    """Regression for fix-wave gap 2: minting straight from _TEMPLATE-contract.template.md without
    deleting its instructional header must refuse with a message naming the actual cause (the
    leftover header), not a garbled path-existence fragment."""
    _init_project(tmp_path)
    text = (
        "<!-- DELETE-THIS-COMMENT-BLOCK-BEFORE-MINTING -- copy THIS file to a new spec (e.g. "
        "ai/contracts/my-change.md) and edit path/to/file.ext references. -->\n\n"
    ) + GOOD_SPEC
    spec = _spec(tmp_path, "leftover-header.md", text)
    result = gov.lint_spec(spec)
    assert not result.ok
    assert any("DELETE-THIS-COMMENT-BLOCK-BEFORE-MINTING" in f for f in result.fatals)
    assert any("instructional header" in f for f in result.fatals)
    # and it must not ALSO produce the old garbled path-existence fragment for the header's own
    # example paths
    assert not any("my-change.md" in f and "referenced path does not exist" in f
                   for f in result.fatals)


def test_lint_spec_passes_when_template_header_is_actually_deleted(tmp_path):
    """Sanity check the fix in the other direction: a spec copied from the template with the
    header properly deleted (per its own instruction) lints clean."""
    _init_project(tmp_path)
    spec = _spec(tmp_path, "clean.md", GOOD_SPEC)
    result = gov.lint_spec(spec)
    assert result.ok, result.fatals


def test_lint_spec_refuses_missing_report_declaration(tmp_path):
    _init_project(tmp_path)
    text = GOOD_SPEC.replace("\nReport: ai/reports/thing-report.md\n", "\n")
    spec = _spec(tmp_path, "no-report.md", text)
    result = gov.lint_spec(spec)
    assert not result.ok
    assert any("report path" in f for f in result.fatals)


def test_lint_spec_missing_file_exits_2(tmp_path):
    rc = gov.main(["--lint-spec", str(tmp_path / "nope.md")])
    assert rc == 2


# ---- ratchet / baseline: not-worse semantics ----

def test_baseline_bootstraps_when_absent(tmp_path):
    bundle = _init_project(tmp_path)
    gov.main(["--open", "q1", str(bundle)])
    gov.main(["--rule", str(next(bundle.glob("open-question_*.md"))), "--verbatim", '"answer"'])
    rc = gov.main([str(bundle), "--baseline"])
    assert rc == 0
    baseline_file = tmp_path / gov.DEFAULT_BASELINE
    assert baseline_file.is_file()
    data = json.loads(baseline_file.read_text(encoding="utf-8"))
    assert data["unverified_notes"] == 1  # the decision note is status: unverified


def test_ratchet_passes_when_count_unchanged(tmp_path):
    bundle = _init_project(tmp_path)
    gov.main([str(bundle), "--baseline"])
    rc = gov.main([str(bundle), "--ratchet"])
    assert rc == 0


def test_ratchet_fails_when_count_rises_above_baseline(tmp_path):
    bundle = _init_project(tmp_path)
    gov.main([str(bundle), "--baseline"])          # baseline = 0 unverified notes
    gov.main(["--open", "q1", str(bundle)])
    gov.main(["--rule", str(next(bundle.glob("open-question_*.md"))), "--verbatim", '"answer"'])
    rc = gov.main([str(bundle), "--ratchet"])
    assert rc == 1                                  # 1 unverified note now > baseline 0


def test_ratchet_passes_when_count_falls_below_baseline(tmp_path):
    bundle = _init_project(tmp_path)
    gov.main(["--open", "q1", str(bundle)])
    gov.main(["--rule", str(next(bundle.glob("open-question_*.md"))), "--verbatim", '"answer"'])
    gov.main([str(bundle), "--baseline"])           # baseline = 1
    (next(bundle.glob("decision_*.md"))).unlink()   # count drops to 0
    rc = gov.main([str(bundle), "--ratchet"])
    assert rc == 0                                   # falling is never a failure


def test_ratchet_with_no_baseline_offers_to_write_one_and_exits_0(tmp_path):
    bundle = _init_project(tmp_path)
    rc = gov.main([str(bundle), "--ratchet"])
    assert rc == 0                                   # day-zero degrade, not a failure


def test_baseline_refuses_to_raise_a_ratcheted_count(tmp_path, capsys):
    """Acceptance test #2: capture the command's own output proving the refusal."""
    bundle = _init_project(tmp_path)
    gov.main([str(bundle), "--baseline"])            # baseline = 0
    gov.main(["--open", "q1", str(bundle)])
    gov.main(["--rule", str(next(bundle.glob("open-question_*.md"))), "--verbatim", '"answer"'])
    capsys.readouterr()                              # discard prior output
    rc = gov.main([str(bundle), "--baseline"])        # would raise 0 -> 1
    out = capsys.readouterr().out
    assert rc == 1
    assert "REFUSED" in out and "DOWNWARD ONLY" in out
    assert "unverified_notes: 0 -> 1" in out
    # and the file on disk must be untouched, still recording the old (lower) count
    data = json.loads((tmp_path / gov.DEFAULT_BASELINE).read_text(encoding="utf-8"))
    assert data["unverified_notes"] == 0


def test_baseline_allows_a_new_lower_value_after_earning_it(tmp_path):
    bundle = _init_project(tmp_path)
    gov.main(["--open", "q1", str(bundle)])
    gov.main(["--rule", str(next(bundle.glob("open-question_*.md"))), "--verbatim", '"answer"'])
    gov.main([str(bundle), "--baseline"])             # baseline = 1
    (next(bundle.glob("decision_*.md"))).unlink()
    rc = gov.main([str(bundle), "--baseline"])         # 0 <= 1, allowed
    assert rc == 0
    data = json.loads((tmp_path / gov.DEFAULT_BASELINE).read_text(encoding="utf-8"))
    assert data["unverified_notes"] == 0


def test_ratchet_grep_rule_from_conf(tmp_path):
    bundle = _init_project(tmp_path)
    # NOTE: the rule's own pattern text ("TODO") lives inside ai/okf.conf, which the scanner also
    # walks -- so the conf line itself contributes one match. That's correct (govern.py doesn't
    # special-case its own config file out of a grep-shaped ratchet rule); the test accounts for it.
    (tmp_path / "ai" / "okf.conf").write_text(
        "govern_ratchet_grep_todo = TODO\n", encoding="utf-8")
    (tmp_path / "scratch.py").write_text("# TODO: one\n# TODO: two\n", encoding="utf-8")
    rc = gov.main([str(bundle), "--baseline"])
    assert rc == 0
    data = json.loads((tmp_path / gov.DEFAULT_BASELINE).read_text(encoding="utf-8"))
    assert data["grep:todo"] == 3                       # 1 in okf.conf + 2 in scratch.py
    (tmp_path / "scratch.py").write_text("# TODO: one\n# TODO: two\n# TODO: three\n", encoding="utf-8")
    rc = gov.main([str(bundle), "--ratchet"])
    assert rc == 1                                     # 4 > baselined 3


# ---- --drift ----

def _write_session(root: Path, session_id: str, human_turns: list[str], *, distilled: str = TODAY,
                    session_dir: str = "ai/session/raw") -> Path:
    """Write a distilled-transcript-shaped .md file (mirrors distill_transcript.py's render())."""
    d = root / session_dir
    d.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"session: {session_id}",
        f"distilled: {distilled}",
        "transcript: fake.jsonl",
        "contains: human + assistant prose only",
        "excluded: tool results, tool calls, reasoning (dropped by block type, not by filtering)",
        "---",
        "",
        f"# Session {session_id[:8]} — {distilled}",
        "",
        "Verbatim conversation, for citing as `source:` from a memory note.",
        "",
    ]
    for t in human_turns:
        lines += ["## Human · 09:00", "", t, "", "## Claude · 09:01", "", "Got it.", ""]
    path = d / f"{session_id}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_drift_day_zero_explains_and_names_the_fix(tmp_path):
    _init_project(tmp_path)
    rc = gov.main(["--drift", str(tmp_path / "ai" / "memory")])
    assert rc == 0


def test_drift_day_zero_output_names_the_fix(tmp_path, capsys):
    _init_project(tmp_path)
    capsys.readouterr()
    rc = gov.main(["--drift", str(tmp_path / "ai" / "memory")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "day zero" in out
    assert "end-session" in out or "distill" in out


def test_drift_off_mode_explains_and_does_not_crash(tmp_path, capsys):
    bundle = _init_project(tmp_path)
    (tmp_path / "ai" / "okf.conf").write_text("archive = off\n", encoding="utf-8")
    capsys.readouterr()
    rc = gov.main(["--drift", str(bundle)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "archive = off" in out


def test_drift_local_mode_gitignored_says_so_not_silent_empty(tmp_path, capsys):
    """R15/brief SS7 trap: on a `local`-mode repo the corpus is gitignored, so a fresh clone (or
    any checkout that never ran a session) sees an empty directory -- --drift must say that
    explicitly rather than reporting a bare 'no drift found' as if the repo has none, ever."""
    bundle = _init_project(tmp_path)
    (tmp_path / "ai" / "okf.conf").write_text("archive = local\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("ai/session/raw/\nai/sessions/raw/\n", encoding="utf-8")
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)
    capsys.readouterr()
    rc = gov.main(["--drift", str(bundle)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "gitignored" in out
    assert "archive = local" in out


def test_drift_surfaces_a_planted_decision_shaped_turn_with_no_note(tmp_path, capsys):
    root = tmp_path
    bundle = _init_project(root)
    _write_session(root, "11111111-aaaa-bbbb-cccc-111111111111",
                    ["Let's use approach A instead of B, it's simpler.", "Sounds good, thanks."])
    capsys.readouterr()
    rc = gov.main(["--drift", str(bundle)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "DRIFT FOUND" in out
    assert "approach A" in out


def test_drift_stops_surfacing_once_a_matching_decision_note_exists(tmp_path, capsys):
    root = tmp_path
    bundle = _init_project(root)
    _write_session(root, "22222222-aaaa-bbbb-cccc-222222222222",
                    ["Let's use approach A instead of B, it's simpler."])
    # A decision note covering the same ruling, sharing real vocabulary with the candidate.
    gov.write_note(
        bundle, type_=gov.DECISION_TYPE, slug="approach-a-vs-b", title="use approach A instead of B",
        description="use approach A instead of B, it's simpler", body="## Decision (Krishna, 2026-07-01)\n\n"
        '"use approach A instead of B, it\'s simpler"\n\n## Why\n\nSimplicity.\n\n## Status\n\nAccepted\n',
        source="ai/scripts/gov", status="unverified", timestamp="2026-01-01T00:00:00Z",
    )
    capsys.readouterr()
    rc = gov.main(["--drift", str(bundle)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRIFT CLEAN" in out


def test_drift_ignores_non_decision_shaped_chatter(tmp_path, capsys):
    root = tmp_path
    bundle = _init_project(root)
    _write_session(root, "33333333-aaaa-bbbb-cccc-333333333333",
                    ["What's the weather like on Mars.", "Can you show me the file contents."])
    rc = gov.main(["--drift", str(bundle)])
    assert rc == 0


def test_drift_only_considers_sessions_newer_than_latest_decision(tmp_path, capsys):
    root = tmp_path
    bundle = _init_project(root)
    # A decision recorded today should suppress drift-scanning an OLDER session entirely, even
    # for an unrelated candidate, since the brief scopes --drift to sessions newer than the
    # latest recorded decision.
    gov.write_note(bundle, type_=gov.DECISION_TYPE, slug="old", title="old ruling",
                    description="old ruling", body="## Decision (Krishna, 2026-07-20)\n\n"
                    '"old ruling"\n\n## Why\n\nx\n\n## Status\n\nAccepted\n',
                    source="ai/scripts/gov", status="unverified", timestamp="2026-07-20T00:00:00Z")
    _write_session(root, "44444444-aaaa-bbbb-cccc-444444444444",
                    ["Let's use approach C instead of D."], distilled="2026-07-01")
    rc = gov.main(["--drift", str(bundle)])
    assert rc == 0  # the session predates the decision cutoff, so it's excluded, not flagged


# ---- --gate ----

def test_gate_composes_okf_gate_drift_and_ratchet_and_passes_when_all_clean(tmp_path, capsys, monkeypatch):
    bundle = _init_project(tmp_path)
    monkeypatch.setattr(gov, "run_okf_gate", lambda b: (0, "GATE: 0 concepts, 0 need changes"))
    rc = gov.main(["--gate", str(bundle)])
    assert rc == 0


def test_gate_names_the_failing_component_when_ratchet_regresses(tmp_path, capsys, monkeypatch):
    bundle = _init_project(tmp_path)
    monkeypatch.setattr(gov, "run_okf_gate", lambda b: (0, "GATE: clean"))
    gov.main([str(bundle), "--baseline"])  # baseline = 0
    gov.main(["--open", "q1", str(bundle)])
    gov.main(["--rule", str(next(bundle.glob("open-question_*.md"))), "--verbatim", '"answer"'])
    capsys.readouterr()
    rc = gov.main(["--gate", str(bundle)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "GATE FAILED" in out
    assert "gov --ratchet" in out


def test_gate_names_the_failing_component_when_okf_gate_fails(tmp_path, capsys, monkeypatch):
    bundle = _init_project(tmp_path)
    monkeypatch.setattr(gov, "run_okf_gate", lambda b: (1, "GATE: 1 concept needs changes"))
    capsys.readouterr()
    rc = gov.main(["--gate", str(bundle)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "GATE FAILED" in out
    assert "okf --gate" in out


def test_gate_names_missing_okf_normalize_as_a_failure_not_a_crash(tmp_path, capsys, monkeypatch):
    bundle = _init_project(tmp_path)
    monkeypatch.setattr(gov, "find_okf_normalize", lambda: None)
    capsys.readouterr()
    rc = gov.main(["--gate", str(bundle)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "okf --gate" in out
    assert "OKF_SKILL_DIR" in out


# ---- config reader ----

def test_read_conf_preserves_value_case_unlike_archive_mode_reader(tmp_path):
    cfg = tmp_path / "okf.conf"
    cfg.write_text("GOVERN_verify_command = Some-Command --Flag\n", encoding="utf-8")
    conf = gov.read_conf(cfg)
    assert conf["govern_verify_command"] == "Some-Command --Flag"  # key folded, value untouched


def test_read_conf_strips_comments_and_ignores_blank_lines(tmp_path):
    cfg = tmp_path / "okf.conf"
    cfg.write_text("# a comment\n\ngovern_base_branch = main  # trailing comment\n", encoding="utf-8")
    conf = gov.read_conf(cfg)
    assert conf["govern_base_branch"] == "main"


def test_version_prints_and_exits_0(capsys):
    rc = gov.main(["--version"])
    out = capsys.readouterr().out
    assert rc == 0 and gov.TOOL_VERSION in out
