"""Tests for audit_knowledge.py (lk-audit-knowledge).

The main fixture reproduces the shape of the BookToSite bundle before its 2026-10-12 memory audit:
a burst of auto-filed report shards (boilerplate `pattern` notes an automation filed in one run,
one per paragraph of one build report), plus healthy notes in both the legacy and the OKF v0.2
frontmatter vocabularies. Every heuristic must fire on
the notes built to trip it and on none of the healthy ones.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import audit_knowledge as ak  # noqa: E402

NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
REPORT = "ai/reports/2026-09-01-clean-stage-report.md"
TRANSCRIPT = "ai/session/raw/029cb3a4.md"

BURST = [f"pattern_2026-09-01-clean-stage-finding-{i}.md" for i in range(8)]
DUP_OLD = "gotcha_merge-gate-refuses-report-without-decisions.md"
DUP_NEW = "gotcha_merge-gate-refuses-a-report-missing-decisions.md"
DEPRECATED = "decision_old-cache-layout.md"
HEALTHY_V02 = ["decision_spine-of-units.md", "runbook_release.md", "reference_source-library.md"]
HEALTHY_LEGACY = "gotcha_wrangler-login-expires.md"
HEALTHY = HEALTHY_V02 + [HEALTHY_LEGACY]

LONG = ("This paragraph carries real, specific content that a reader cannot get from the title "
        "alone: the exact command, the failure it prevents, the file it touches and the reason "
        "the rule exists, written by a person who checked it against the code on the day. ")

BURST_SUBJECTS = ["renderer port", "cleanup rules path", "outbox events", "test fakes",
                  "report file", "page lookup", "factory wiring", "journal format"]


def _write(path: Path, fm: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip()
    path.write_text(f"---\n{fm_text}\n---\n\n{body}", encoding="utf-8")


def _v02(type_, title, desc, source, *, created="2026-08-01", status="stable", stale_after=None,
         relations=None):
    fm = {"type": type_, "title": title, "description": desc,
          "generated": {"by": "claude-code/claude-opus-5-5", "at": f"{created}T10:00:00Z"},
          "created": created, "sources": [{"resource": source}], "status": status}
    if status == "stable":
        fm["verified"] = [{"by": "human:krishna", "at": f"{created}T12:00:00Z"}]
        fm["stale_after"] = stale_after or "2027-06-01T00:00:00Z"
    elif stale_after:
        fm["stale_after"] = stale_after
    if relations:
        fm["relations"] = relations
    return fm


def _burst_note(i: int) -> tuple[dict, str]:
    """One auto-filed report shard: a report paragraph plus the filer's fixed boilerplate lines."""
    subject = BURST_SUBJECTS[i]
    para = f"**The {subject} moved** to its own module, which the brief allows."
    fm = {"type": "pattern", "title": f"**The {subject} moved** to its own module",
          "description": para[:120], "timestamp": "2026-09-01T20:15:53Z", "created": "2026-09-01",
          "source": REPORT, "status": "unverified"}
    body = (f"## Decision (report 2026-09-01-clean-stage, 2026-09-01)\n\n{para}\n\n## Why\n\n"
            "Recorded automatically from the build's own completion report at filing time.\n\n"
            "## Status\n\nAccepted (agent-authored; not a human ruling).\n\n"
            f"**Verify:** re-read {REPORT} (the report this was filed from).\n")
    return fm, body


def build_bundle(root: Path) -> Path:
    """The BookToSite-shaped fixture. Returns the bundle dir (root/ai/memory)."""
    b = root / "ai" / "memory"
    for i, name in enumerate(BURST):
        _write(b / name, *_burst_note(i))

    # Two near-duplicates: same fact filed twice, a month apart, different sources.
    _write(b / DUP_OLD, _v02(
        "gotcha", "Build merge gate refuses a completion report without a Decisions section",
        "The merge gate refuses a build completion report lacking a Decisions section heading",
        "ai/session/2026-08-01-wave-1.md", created="2026-08-01"),
        LONG + "See [the release runbook](runbook_release.md).\n\n**Verify:** `grep -n Decisions merge_gate.py`\n")
    _write(b / DUP_NEW, _v02(
        "gotcha", "Merge gate refuses a build completion report missing its Decisions section",
        "The merge gate refuses a completion report without a Decisions section heading",
        "ai/session/2026-09-15-wave-2.md", created="2026-09-15"),
        LONG + "\n**Verify:** `grep -n Decisions merge_gate.py`\n")

    # A deprecated note that a healthy note still links to (a real, non-historical link).
    _write(b / DEPRECATED, _v02(
        "decision", "Work-tier cache lives beside the vault", "Superseded layout for the work tier",
        "ai/plans/old-layout.md", status="deprecated"),
        LONG + "\n**Verify:** n/a, deprecated.\n")

    # Healthy v0.2 notes, linked in a ring (and to the near-dups and the deprecated note).
    _write(b / HEALTHY_V02[0], _v02(
        "decision", "The Spine of units is the central artifact",
        "Logical units with anchors replace page ranges", "ai/reviews/2026-08-01-synthesis.md"),
        LONG + f"See [runbook](runbook_release.md), [old layout]({DEPRECATED}) and [dup]({DUP_NEW}).\n\n"
        "**Verify:** `grep -n Spine docs/architecture.md`\n")
    _write(b / HEALTHY_V02[1], _v02(
        "runbook", "Release a book site", "Build, check and deploy one site",
        TRANSCRIPT, relations=["relates reference_source-library.md"]),
        LONG + f"Related: [wrangler]({HEALTHY_LEGACY}) and [old dup]({DUP_OLD}).\n\n**Verify:** run the release dry run\n")
    _write(b / HEALTHY_V02[2], _v02(
        "reference", "Where the source library lives", "Vault path and its frozen copy", TRANSCRIPT),
        LONG + "[Spine of units](decision_spine-of-units.md).\n\n**Verify:** `ls D:/Vaults`\n")

    # Healthy note in the LEGACY vocabulary.
    _write(b / HEALTHY_LEGACY, {
        "type": "gotcha", "title": "wrangler's OAuth login expires after idle months",
        "description": "Deploy fails with Not logged in; only Krishna can renew it",
        "timestamp": "2026-08-01T00:00:00Z", "created": "2026-08-01",
        "source": f"{TRANSCRIPT}; ai/session/2026-08-01-wave-1.md",
        "status": "verified", "verified_on": "2026-08-01"},
        LONG + "Related: [release](runbook_release.md).\n\n**Verify:** `npx wrangler whoami`\n")

    # Reserved and backup files that must never be read as concepts.
    (b / "index.md").write_text("# Index\n\n" + "".join(f"* [{n}]({n})\n" for n in BURST), encoding="utf-8")
    (b.parent / ".okf-backups" / "x").mkdir(parents=True)
    _write(b / ".okf-backups" / "old" / BURST[0], *_burst_note(0))
    return b


@pytest.fixture
def bundle(tmp_path):
    return build_bundle(tmp_path)


def _kind(result, kind):
    return [f for f in result["findings"] if f["kind"] == kind]


def _flagged(result, kind):
    return {n for f in _kind(result, kind) for n in f["notes"]}


# --------------------------------------------------------------------------- heuristics


def test_loads_concepts_only(bundle):
    r = ak.audit(bundle, now=NOW)
    assert r["notes"] == len(BURST) + 2 + 1 + len(HEALTHY)
    assert r["malformed"] == []


def test_burst_catches_the_auto_filed_cluster(bundle):
    r = ak.audit(bundle, now=NOW)
    clusters = _kind(r, "BURST")
    assert len(clusters) == 1
    assert set(clusters[0]["notes"]) == set(BURST)
    assert REPORT in clusters[0]["reason"]


def test_low_info_fires_on_boilerplate_shards_only(bundle):
    r = ak.audit(bundle, now=NOW)
    assert _flagged(r, "LOW_INFO") == set(BURST)


def test_low_info_title_echo_rule(tmp_path):
    b = tmp_path / "ai" / "memory"
    text = ("A dry run writes nothing in the work tier either; reads still see real work files "
            "and every stage honours it, including the clean report that runs last of all here")
    _write(b / "pattern_echo.md", {"type": "pattern", "title": text[:80], "description": text[:120],
                                   "created": "2026-09-01", "source": REPORT, "status": "unverified"},
           text + ".\n\n**Verify:** re-read the report\n")
    r = ak.audit(b, now=NOW)
    (f,) = _kind(r, "LOW_INFO")
    assert "restates" in f["reason"]


def test_near_dup_pairs_the_duplicates_and_keeps_the_older(bundle):
    r = ak.audit(bundle, now=NOW)
    pairs = _kind(r, "NEAR_DUP")
    assert [set(p["notes"]) for p in pairs] == [{DUP_OLD, DUP_NEW}]
    plan = {row["path"]: row["action"] for row in r["plan"]}
    assert plan[DUP_NEW] == f"merge-into:{DUP_OLD}"
    assert plan[DUP_OLD] == "keep"


def test_stale_reports_deprecated_note_with_inbound_link(bundle):
    r = ak.audit(bundle, now=NOW)
    (f,) = _kind(r, "STALE")
    assert f["notes"] == [DEPRECATED]
    assert HEALTHY_V02[0] in f["reason"]


def test_stale_after_passed_and_legacy_stale(tmp_path):
    b = tmp_path / "ai" / "memory"
    _write(b / "gotcha_expired.md", _v02("gotcha", "Expired", "x", "a/b.md",
                                         stale_after="2026-09-01T00:00:00Z"), LONG)
    _write(b / "gotcha_legacy-stale.md", {"type": "gotcha", "title": "Old", "description": "y",
                                          "source": "a/c.md", "status": "stale"}, LONG)
    r = ak.audit(b, now=NOW)
    assert _flagged(r, "STALE") == {"gotcha_expired.md", "gotcha_legacy-stale.md"}
    plan = {row["path"]: row["action"] for row in r["plan"]}
    assert plan["gotcha_expired.md"] == plan["gotcha_legacy-stale.md"] == "deprecate"


def test_superseded_note_linked_only_by_its_superseder_is_not_stale(tmp_path):
    b = tmp_path / "ai" / "memory"
    oq = "open-question_how-big.md"
    _write(b / oq, {"type": "open-question", "title": "How big?", "description": "q",
                    "source": "a/b.md", "status": "closed",
                    "relations": ["relates decision_how-big.md"]}, LONG)
    _write(b / "decision_how-big.md", {"type": "decision", "title": "Small", "description": "r",
                                       "source": "a/b.md", "status": "verified",
                                       "relations": [f"supersedes {oq}"]},
           LONG + f"Closes [the question]({oq}).\n")
    r = ak.audit(b, now=NOW)
    assert _kind(r, "STALE") == []


def test_never_promoted(bundle):
    r = ak.audit(bundle, now=NOW)
    # The burst notes are legacy `unverified`, filed 2026-09-01: 41 days before NOW.
    assert _flagged(r, "NEVER_PROMOTED") == set(BURST)


def test_never_promoted_v02_draft(tmp_path):
    b = tmp_path / "ai" / "memory"
    _write(b / "gotcha_old-draft.md", _v02("gotcha", "Old draft", "d", "a/b.md",
                                           created="2026-08-01", status="draft"), LONG)
    _write(b / "gotcha_new-draft.md", _v02("gotcha", "New draft", "e", "a/c.md",
                                           created="2026-10-01", status="draft"), LONG)
    r = ak.audit(b, now=NOW)
    assert _flagged(r, "NEVER_PROMOTED") == {"gotcha_old-draft.md"}
    assert {row["path"]: row["action"] for row in r["plan"]}["gotcha_old-draft.md"] == "promote"


def test_never_promoted_open_question_is_answered_not_promoted(tmp_path):
    # An old open question is an undecided fork: the fix is a decision note, not a promotion.
    b = tmp_path / "ai" / "memory"
    oq = "open-question_which-cache.md"
    _write(b / oq, _v02("open-question", "Which cache layout?", "q", "a/b.md",
                        created="2026-08-01", status="draft"), LONG)
    r = ak.audit(b, now=NOW)
    assert _flagged(r, "NEVER_PROMOTED") == {oq}
    (row,) = [row for row in r["plan"] if row["path"] == oq]
    assert row["action"] == "keep"
    assert row["reason"].startswith(
        "NEVER_PROMOTED: open question still a draft after 72 days (status: draft): undecided fork: "
        "answer it with a decision note that supersedes it, then deprecate this one")


def test_orphans_are_the_unlinked_notes_only(bundle):
    r = ak.audit(bundle, now=NOW)
    # index.md links every burst note, but index.md does not count as an inbound link.
    assert _flagged(r, "ORPHAN") == set(BURST)


def test_no_heuristic_fires_on_healthy_notes(bundle):
    r = ak.audit(bundle, now=NOW)
    for f in r["findings"]:
        assert not set(f["notes"]) & set(HEALTHY), f
    assert not {row["path"] for row in r["plan"]} & set(HEALTHY)


def test_hand_distilled_session_cluster_is_not_a_burst(tmp_path):
    """Six healthy notes of mixed types citing one transcript on one day is end-session
    working as designed (measured on BookToSite), not a machine burst."""
    b = tmp_path / "ai" / "memory"
    for i, t in enumerate(["gotcha", "gotcha", "runbook", "runbook", "reference", "decision"]):
        _write(b / f"{t}_topic-{i}.md", _v02(t, f"Topic {i} title", f"desc {i}",
                                             f"{TRANSCRIPT} (Human 17:4{i})", created="2026-10-12"),
               LONG)
    r = ak.audit(b, now=NOW)
    assert _kind(r, "BURST") == []


def test_oversized_type(tmp_path):
    b = tmp_path / "ai" / "memory"
    for i in range(14):
        _write(b / f"pattern_p{i}.md", _v02("pattern", f"P {i} alpha{i}", f"d{i}", f"s/{i}.md"), LONG)
    for i in range(6):
        _write(b / f"gotcha_g{i}.md", _v02("gotcha", f"G {i} beta{i}", f"e{i}", f"t/{i}.md"), LONG)
    r = ak.audit(b, now=NOW)
    (f,) = _kind(r, "OVERSIZED_TYPE")
    assert "pattern" in f["reason"] and "14 of 20" in f["reason"]


def test_oversized_type_needs_twenty_notes(bundle):
    assert _kind(ak.audit(bundle, now=NOW), "OVERSIZED_TYPE") == []


def test_malformed_yaml_is_skipped_and_reported(bundle):
    (bundle / "gotcha_broken.md").write_text("---\ntitle: [unclosed\n---\nbody\n", encoding="utf-8")
    (bundle / "gotcha_nofm.md").write_text("just text\n", encoding="utf-8")
    r = ak.audit(bundle, now=NOW)
    assert {m["path"] for m in r["malformed"]} == {"gotcha_broken.md", "gotcha_nofm.md"}
    assert r["notes"] == len(BURST) + 2 + 1 + len(HEALTHY)


# --------------------------------------------------------------------------- report / json / plan


def test_report_text_and_summary_line(bundle, capsys):
    assert ak.main([str(bundle)]) == 0
    out = capsys.readouterr().out
    for kind in ("BURST", "LOW_INFO", "NEAR_DUP", "STALE", "NEVER_PROMOTED", "ORPHAN"):
        assert kind in out
    last = out.strip().splitlines()[-1]
    assert last.startswith("summary:") and "BURST 1" in last


def test_json_output(bundle, capsys):
    assert ak.main([str(bundle), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["notes"] == len(BURST) + 2 + 1 + len(HEALTHY)
    assert {f["kind"] for f in data["findings"]} >= {"BURST", "LOW_INFO", "NEAR_DUP", "STALE"}


def test_plan_shape(bundle, tmp_path):
    out = tmp_path / "plan.md"
    assert ak.main([str(bundle), "--plan", str(out)]) == 0
    rows, errors = ak.parse_plan(out.read_text(encoding="utf-8"))
    assert errors == []
    actions = {r.path: r.action for r in rows}
    for name in BURST:
        assert actions[name] == "delete"
    assert actions[DUP_NEW] == "merge-into" and actions[DUP_OLD] == "keep"
    assert actions[DEPRECATED] == "keep"
    assert not set(actions) & set(HEALTHY)
    for r in rows:
        assert r.action in ak.ACTIONS
        assert r.reason
    text = out.read_text(encoding="utf-8")
    assert "| action | path | reason |" in text


def test_plan_refuses_to_write_inside_the_bundle(bundle):
    assert ak.main([str(bundle), "--plan", str(bundle / "plan.md")]) == 2
    assert not (bundle / "plan.md").exists()


# --------------------------------------------------------------------------- apply


def _plan(tmp_path, bundle, rows):
    p = tmp_path / "plan.md"
    body = "\n".join(f"| {a} | {path} | test |" for a, path in rows)
    p.write_text(f"# plan\n\n| action | path | reason |\n|---|---|---|\n{body}\n", encoding="utf-8")
    return p


def test_apply_delete_outside_git_moves_to_backups(bundle, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ak, "find_git_root", lambda start: None)
    plan = _plan(tmp_path, bundle, [("delete", BURST[0]), ("keep", BURST[1])])
    assert ak.main([str(bundle), "--apply", str(plan)]) == 0
    assert not (bundle / BURST[0]).exists()
    assert (bundle / BURST[1]).exists()
    moved = list((bundle.parent / ".okf-backups").glob(f"audit-*/{BURST[0]}"))
    assert len(moved) == 1
    out = capsys.readouterr().out
    assert "now run: ai/scripts/okf --reindex && ai/scripts/okf --check" in out


def test_apply_delete_is_idempotent(bundle, tmp_path, monkeypatch):
    monkeypatch.setattr(ak, "find_git_root", lambda start: None)
    plan = _plan(tmp_path, bundle, [("delete", BURST[0])])
    assert ak.main([str(bundle), "--apply", str(plan)]) == 0
    assert ak.main([str(bundle), "--apply", str(plan)]) == 0


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_apply_delete_inside_git_uses_git_rm(bundle, tmp_path):
    root = tmp_path
    git = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run(git[:3] + ["init", "-q"], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "fixture"], check=True)
    plan = root.parent / f"{root.name}-plan.md"
    plan.write_text(f"| delete | {BURST[2]} | junk |\n", encoding="utf-8")
    assert ak.main([str(bundle), "--apply", str(plan)]) == 0
    status = subprocess.run(git[:3] + ["status", "--porcelain"], capture_output=True, text=True).stdout
    assert f"D  ai/memory/{BURST[2]}" in status
    assert not list((bundle.parent / ".okf-backups").glob("audit-*"))   # git rm, not a backup move


def test_apply_deprecate_rewrites_status_and_preserves_the_rest(bundle, tmp_path):
    target = bundle / HEALTHY_V02[2]
    before_fm, before_body = ak.parse_frontmatter(target.read_text(encoding="utf-8"))[:2]
    plan = _plan(tmp_path, bundle, [("deprecate", HEALTHY_V02[2])])
    assert ak.main([str(bundle), "--apply", str(plan)]) == 0
    after_fm, after_body = ak.parse_frontmatter(target.read_text(encoding="utf-8"))[:2]
    assert after_fm["status"] == "deprecated"
    assert list(after_fm) == list(before_fm)
    assert {k: v for k, v in after_fm.items() if k != "status"} == \
           {k: v for k, v in before_fm.items() if k != "status"}
    assert after_body == before_body


def test_apply_deprecate_inserts_missing_status_in_key_order(tmp_path):
    b = tmp_path / "ai" / "memory"
    p = b / "gotcha_no-status.md"
    b.mkdir(parents=True)
    p.write_bytes(b"---\r\ntype: gotcha\r\ntitle: T\r\nsources:\r\n- resource: a/b.md\r\n"
                  b"relations:\r\n- relates x.md\r\n---\r\n\r\nBody\r\n")
    plan = _plan(tmp_path, b, [("deprecate", p.name)])
    assert ak.main([str(b), "--apply", str(plan)]) == 0
    raw = p.read_bytes()
    assert b"\r\nstatus: deprecated\r\nrelations:" in raw          # before `relations`, CRLF kept
    assert list(ak.parse_frontmatter(raw.decode())[0]) == ["type", "title", "sources", "status", "relations"]


def test_apply_refuses_path_escape_and_applies_nothing(bundle, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ak, "find_git_root", lambda start: None)
    outside = tmp_path / "outside.md"
    outside.write_text("keep me\n", encoding="utf-8")
    plan = _plan(tmp_path, bundle, [("delete", BURST[0]), ("delete", "../../outside.md"),
                                    ("delete", str(outside))])
    assert ak.main([str(bundle), "--apply", str(plan)]) == 2
    assert outside.exists() and (bundle / BURST[0]).exists()
    out = capsys.readouterr().out
    assert "outside the bundle" in out and "nothing was applied" in out


def test_apply_refuses_reserved_and_unknown_action(bundle, tmp_path):
    plan = _plan(tmp_path, bundle, [("delete", "index.md"), ("obliterate", BURST[0])])
    assert ak.main([str(bundle), "--apply", str(plan)]) == 2
    assert (bundle / "index.md").exists() and (bundle / BURST[0]).exists()


def test_apply_merge_and_promote_only_print(bundle, tmp_path, capsys):
    before = {p: p.read_bytes() for p in bundle.rglob("*.md")}
    plan = _plan(tmp_path, bundle, [(f"merge-into:{DUP_OLD}", DUP_NEW), ("promote", BURST[3])])
    assert ak.main([str(bundle), "--apply", str(plan)]) == 0
    assert {p: p.read_bytes() for p in bundle.rglob("*.md")} == before
    out = capsys.readouterr().out
    assert DUP_OLD in out and DUP_NEW in out and "okf --promote" in out


def test_apply_refuses_plan_written_for_another_bundle(bundle, tmp_path):
    out = tmp_path / "plan.md"
    assert ak.main([str(bundle), "--plan", str(out)]) == 0
    other = build_bundle(tmp_path / "other")
    assert ak.main([str(other), "--apply", str(out)]) == 2
    assert all((other / n).exists() for n in BURST)


def test_help_runs():
    r = subprocess.run([sys.executable, str(HERE / "audit_knowledge.py"), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "--apply" in r.stdout
