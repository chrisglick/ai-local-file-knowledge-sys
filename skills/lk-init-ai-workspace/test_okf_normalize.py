"""Tests for okf_normalize.py (OKF v0.2 vocabulary + legacy migration).
Run: pytest test_okf_normalize.py -q  (deps: pytest, pyyaml)."""
from pathlib import Path

import pytest

import okf_normalize as okf

TODAY = "2026-06-17"
ACTOR = "human:tester"

# A clean v0.2 note's frontmatter (no status => stable per spec, no verified needed).
V02 = ("type: schema\ntitle: {t}\ndescription: {d}\n"
       "generated:\n  by: human:tester\n  at: '2026-01-01T00:00:00Z'\n"
       "created: '2026-01-01'\nsources:\n  - resource: s\n")


def write(p: Path, fm_lines: str, body: str = "body\n\n**Verify:** run x\n"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\n{fm_lines}\n---\n\n{body}", encoding="utf-8")


def v02(t="T", d="d", extra=""):
    return V02.format(t=t, d=d) + extra


# ---- frontmatter round-trip ----

def test_parse_roundtrip_preserves_body_and_orders_keys():
    text = "---\nstatus: stable\ntype: schema\ntitle: T\n---\n\nhello\n"
    fm, body = okf.parse_frontmatter(text)
    assert fm["type"] == "schema" and body.strip() == "hello"
    out = okf.serialize(fm, body)
    # type comes before status per KEY_ORDER, regardless of input order
    assert out.index("type:") < out.index("status:")
    fm2, body2 = okf.parse_frontmatter(out)
    assert fm2 == fm and body2.strip() == "hello"


def test_key_order_matches_contract():
    assert okf.KEY_ORDER == ["type", "title", "description", "resource", "tags",
                             "generated", "created", "valid_as_of", "sources", "status",
                             "verified", "stale_after", "relations"]


def test_parse_no_frontmatter_returns_none():
    fm, body = okf.parse_frontmatter("# just a heading\n")
    assert fm is None


def test_parse_malformed_yaml_does_not_raise():
    # unquoted source value with a colon — invalid YAML; must NOT crash, returns None
    bad = "---\ntype: pattern\nsource: session 2026-06-12 (Sam: left/right diverge)\n---\n\nbody\n"
    fm, body = okf.parse_frontmatter(bad)
    assert fm is None


def test_malformed_note_does_not_crash_run_and_others_still_processed(tmp_path):
    write(tmp_path / "schema_good.md", v02(t="Good"))
    (tmp_path / "pattern_bad.md").write_text(
        "---\ntype: pattern\nsource: session (Sam: left/right)\n---\n\nb\n", encoding="utf-8")
    rc = okf.main([str(tmp_path), "--actor", ACTOR])   # bare run — must complete, not crash
    assert rc == 1                                      # the malformed note is an error -> nonzero
    okf.reindex(tmp_path)
    assert "schema_good.md" in (tmp_path / "index.md").read_text(encoding="utf-8")


def test_reference_is_a_valid_type():
    assert "reference" in okf.TYPE_ENUM
    new, changes, errors = okf.normalize_fm(
        {"type": "reference", "title": "T", "description": "d"}, {}, "reference_x.md", today=TODAY)
    assert not any("outside our enum" in c for c in changes)
    assert okf._slug_token("reference_pipeline-tools") == "pipeline"


# ---- v0.2 migration (the 0.9 change) ----

def test_migrate_timestamp_to_generated():
    fm = {"type": "schema", "title": "T", "description": "d", "timestamp": "2026-06-11T10:00:00Z",
          "created": "2026-06-11"}
    new, changes, errors = okf.normalize_fm(fm, {}, "schema_x.md", today=TODAY, actor=ACTOR)
    assert "timestamp" not in new
    assert new["generated"] == {"by": ACTOR, "at": "2026-06-11T10:00:00Z"}
    assert any("generated.at" in c for c in changes) and not errors


def test_migrate_updated_to_generated_and_backfill_created():
    fm = {"type": "schema", "title": "T", "updated": "2026-06-11"}
    desc = {"schema_x.md": "the hook"}
    new, changes, errors = okf.normalize_fm(fm, desc, "schema_x.md", today=TODAY, actor=ACTOR)
    assert "updated" not in new and "timestamp" not in new
    assert new["generated"]["at"] == "2026-06-11T00:00:00Z"
    assert new["created"] == "2026-06-11"          # backfilled from generated.at, set-once
    assert new["description"] == "the hook"
    assert not errors


def test_timestamp_wins_over_updated_and_both_are_dropped():
    fm = {"type": "schema", "title": "T", "description": "d",
          "timestamp": "2026-06-11T00:00:00Z", "updated": "2026-06-15", "created": "2026-06-11"}
    new, changes, errors = okf.normalize_fm(fm, {}, "f.md", today=TODAY, actor=ACTOR)
    assert "updated" not in new and "timestamp" not in new
    assert new["generated"]["at"] == "2026-06-11T00:00:00Z"


def test_generated_by_is_added_when_missing():
    fm = {"type": "schema", "title": "T", "description": "d", "generated": {"at": "2026-06-11T00:00:00Z"}}
    new, changes, _ = okf.normalize_fm(fm, {}, "f.md", today=TODAY, actor="process:x")
    assert new["generated"]["by"] == "process:x"
    assert any("generated.by" in c for c in changes)


def test_migrate_source_string_to_sources_list_splits_on_semicolon():
    fm = {"type": "schema", "title": "T", "description": "d", "source": "a.py:12; docs/b.md"}
    new, changes, errors = okf.normalize_fm(fm, {}, "f.md", today=TODAY, actor=ACTOR)
    assert "source" not in new
    assert new["sources"] == [{"resource": "a.py:12"}, {"resource": "docs/b.md"}]
    assert not errors


def test_sources_entries_coerced_and_missing_resource_is_error():
    fm = {"type": "schema", "title": "T", "description": "d", "sources": ["a.py", {"id": "x"}]}
    new, changes, errors = okf.normalize_fm(fm, {}, "f.md", today=TODAY, actor=ACTOR)
    assert new["sources"][0] == {"resource": "a.py"}
    assert any("missing `resource`" in e for e in errors)


@pytest.mark.parametrize("legacy,expected", [
    ("unverified", "draft"), ("verified", "stable"), ("stale", "deprecated"),
    ("open", "draft"), ("closed", "deprecated"),
])
def test_migrate_legacy_status(legacy, expected):
    fm = {"type": "schema", "title": "T", "description": "d", "status": legacy}
    new, changes, errors = okf.normalize_fm(fm, {}, "f.md", today=TODAY, actor=ACTOR)
    assert new["status"] == expected and not errors
    assert any(f"`{legacy}` -> `{expected}`" in c for c in changes)


def test_invalid_status_is_error_and_spec_values_pass_untouched():
    bad, _, errors = okf.normalize_fm({"type": "schema", "title": "T", "description": "d",
                                       "status": "wip"}, {}, "f.md", today=TODAY)
    assert any("not in the OKF enum" in e for e in errors)
    for ok in ("draft", "stable", "deprecated"):
        new, changes, errors = okf.normalize_fm({"type": "schema", "title": "T", "description": "d",
                                                 "status": ok}, {}, "f.md", today=TODAY)
        assert new["status"] == ok and not errors and not any("status" in c for c in changes)


def test_migrate_verified_on_to_verified_list_and_stale_after():
    fm = {"type": "schema", "title": "T", "description": "d", "status": "verified",
          "verified_on": "2026-01-01"}
    new, changes, errors = okf.normalize_fm(fm, {}, "f.md", today=TODAY, actor=ACTOR)
    assert "verified_on" not in new
    assert new["status"] == "stable"
    assert new["verified"] == [{"by": ACTOR, "at": "2026-01-01T00:00:00Z"}]
    assert new["stale_after"] == "2026-04-01T00:00:00Z"        # +90 days
    assert not errors


def test_bare_verified_mapping_becomes_list():
    fm = {"type": "schema", "title": "T", "description": "d",
          "verified": {"by": "human:a", "at": "2026-01-01T00:00:00Z"}}
    new, changes, _ = okf.normalize_fm(fm, {}, "f.md", today=TODAY)
    assert new["verified"] == [{"by": "human:a", "at": "2026-01-01T00:00:00Z"}]


def test_clean_v02_note_has_no_changes():
    fm = {"type": "schema", "title": "T", "description": "d",
          "generated": {"by": "human:a", "at": "2026-01-01T00:00:00Z"}, "created": "2026-01-01",
          "sources": [{"resource": "s"}], "status": "draft"}
    new, changes, errors = okf.normalize_fm(fm, {}, "schema_x.md", today=TODAY)
    assert changes == [] and errors == [] and new == fm


def test_legacy_bundle_migrates_end_to_end_and_then_checks_clean(tmp_path):
    write(tmp_path / "schema_a.md",
          "type: schema\ntitle: A\ndescription: d\ntimestamp: 2026-01-01T00:00:00Z\n"
          "created: 2026-01-01\nsource: s\nstatus: unverified")
    assert okf.main([str(tmp_path), "--gate", "--actor", ACTOR]) == 1      # legacy keys = drift
    assert okf.main([str(tmp_path), "--apply", "--no-backup", "--actor", ACTOR]) == 0
    fm, _ = okf.parse_frontmatter((tmp_path / "schema_a.md").read_text(encoding="utf-8"))
    for legacy in okf.LEGACY_KEYS:
        assert legacy not in fm
    assert fm["generated"] == {"by": ACTOR, "at": "2026-01-01T00:00:00Z"}
    assert fm["sources"] == [{"resource": "s"}] and fm["status"] == "draft"
    okf.reindex(tmp_path)
    assert okf.main([str(tmp_path), "--check", "--actor", ACTOR]) == 0     # fully conformant now


# ---- actor resolution ----

def test_actor_override_then_conf_then_default(tmp_path, monkeypatch):
    bundle = tmp_path / "ai" / "memory"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(okf, "_git_user_name", lambda cwd: None)
    assert okf.resolve_actor(bundle) == okf.DEFAULT_ACTOR
    (tmp_path / "ai" / "okf.conf").write_text("# c\narchive = local\nactor = human:krishna\n", encoding="utf-8")
    assert okf.resolve_actor(bundle) == "human:krishna"
    assert okf.resolve_actor(bundle, "process:x") == "process:x"


def test_actor_from_git_user_name_is_slugified(tmp_path, monkeypatch):
    monkeypatch.setattr(okf, "_git_user_name", lambda cwd: "Chris Glick")
    assert okf.resolve_actor(tmp_path) == "human:chris-glick"


# ---- review / promote ----

def test_review_lists_draft_and_legacy_unverified_only(tmp_path):
    write(tmp_path / "schema_a.md", v02(t="A", extra="status: draft\n"))
    write(tmp_path / "schema_b.md", v02(t="B", extra="status: stable\n"))
    write(tmp_path / "schema_c.md", v02(t="C", extra="status: unverified\n"))   # mid-migration
    write(tmp_path / "sub" / "schema_d.md", v02(t="D", extra="status: draft\n"))  # nested counts
    rows = okf.review_drafts(tmp_path)
    assert {p.name for p, _ in rows} == {"schema_a.md", "schema_c.md", "schema_d.md"}
    assert okf.main([str(tmp_path), "--review"]) == 0                   # read-only, exits 0


def test_promote_writes_stable_verified_and_stale_after(tmp_path):
    write(tmp_path / "schema_a.md", v02(t="A", extra="status: draft\n"))
    done = okf.promote_notes([tmp_path / "schema_a.md"], actor="human:k", now="2026-06-17T12:00:00Z")
    assert done
    fm, body = okf.parse_frontmatter((tmp_path / "schema_a.md").read_text(encoding="utf-8"))
    assert fm["status"] == "stable"
    assert fm["verified"] == [{"by": "human:k", "at": "2026-06-17T12:00:00Z"}]
    assert fm["stale_after"] == "2026-09-15T00:00:00Z"
    assert "**Verify:**" in body                                          # body untouched
    # second promotion appends, never replaces (a verification history)
    okf.promote_notes([tmp_path / "schema_a.md"], actor="human:k", now="2026-07-01T00:00:00Z")
    fm, _ = okf.parse_frontmatter((tmp_path / "schema_a.md").read_text(encoding="utf-8"))
    assert len(fm["verified"]) == 2


def test_promote_cli_refuses_non_human_actor(tmp_path):
    write(tmp_path / "schema_a.md", v02(t="A", extra="status: draft\n"))
    assert okf.main([str(tmp_path), "--promote", str(tmp_path / "schema_a.md"), "--actor", "process:bot"]) == 2
    assert okf.main([str(tmp_path), "--promote", str(tmp_path / "schema_a.md"), "--actor", "human:k"]) == 0


# ---- suggest-links (v0.7) ----

def test_suggest_links_surfaces_unlinked_pair_and_excludes_linked(tmp_path):
    write(tmp_path / "schema_invoice_api.md", v02(t="Invoice API", d="invoice payment fields", extra="status: draft\n"))
    write(tmp_path / "schema_invoice_db.md", v02(t="Invoice DB", d="invoice payment table", extra="status: draft\n"))
    write(tmp_path / "schema_widget.md", v02(t="Widget", d="ui widget toggle", extra="status: draft\n"))
    pairs = okf.suggest_links(tmp_path, min_score=1)
    names = {frozenset({pa.name, pb.name}) for _s, pa, pb, _sh in pairs}
    assert frozenset({"schema_invoice_api.md", "schema_invoice_db.md"}) in names
    text = (tmp_path / "schema_invoice_api.md").read_text(encoding="utf-8")
    (tmp_path / "schema_invoice_api.md").write_text(
        text.replace("status: draft", "status: draft\nrelations:\n  - relates schema_invoice_db.md"),
        encoding="utf-8")
    pairs2 = okf.suggest_links(tmp_path, min_score=1)
    names2 = {frozenset({pa.name, pb.name}) for _s, pa, pb, _sh in pairs2}
    assert frozenset({"schema_invoice_api.md", "schema_invoice_db.md"}) not in names2
    assert okf.main([str(tmp_path), "--suggest-links"]) == 0


# ---- types ----

def test_workaround_and_open_question_are_valid_types():
    for t in ("workaround", "open-question"):
        assert t in okf.TYPE_ENUM
        new, changes, errors = okf.normalize_fm(
            {"type": t, "title": "T", "description": "d"}, {}, f"{t}_x.md", today=TODAY)
        assert not any("outside our enum" in c for c in changes)


def test_relations_typed_and_validated(tmp_path):
    (tmp_path / "schema_target.md").write_text("---\ntype: schema\n---\nx\n", encoding="utf-8")
    note = tmp_path / "decision_x.md"
    base = {"type": "decision", "title": "X", "description": "d", "sources": [{"resource": "s"}]}
    body = "b\n\n**Verify:** y\n"
    ok = okf.check_provenance({**base, "relations": ["supersedes schema_target.md"]}, body, note, tmp_path, today=TODAY)
    assert not any("relation" in w for w in ok)
    bad_verb = okf.check_provenance({**base, "relations": ["frobnicates schema_target.md"]}, body, note, tmp_path, today=TODAY)
    assert any("verb in" in w for w in bad_verb)
    broken = okf.check_provenance({**base, "relations": ["supersedes missing.md"]}, body, note, tmp_path, today=TODAY)
    assert any("relation target not found" in w for w in broken)


# ---- trust / lifecycle checks ----

def test_verified_decay_warns_when_no_stale_after(tmp_path):
    note = tmp_path / "schema_x.md"
    base = {"type": "schema", "title": "X", "description": "d", "sources": [{"resource": "s"}],
            "status": "stable"}
    body = "b\n\n**Verify:** y\n"
    old = okf.check_provenance({**base, "verified": [{"by": "human:a", "at": "2026-01-01T00:00:00Z"}]},
                               body, note, tmp_path, today="2026-06-18")
    assert any("decays" in w for w in old)
    fresh = okf.check_provenance({**base, "verified": [{"by": "human:a", "at": "2026-06-17T00:00:00Z"}]},
                                 body, note, tmp_path, today="2026-06-18")
    assert not any("decays" in w for w in fresh)


def test_stale_after_passed_warns_and_future_does_not(tmp_path):
    note = tmp_path / "schema_x.md"
    base = {"type": "schema", "title": "X", "description": "d", "sources": [{"resource": "s"}],
            "verified": [{"by": "human:a", "at": "2026-01-01T00:00:00Z"}]}
    body = "b\n\n**Verify:** y\n"
    past = okf.check_provenance({**base, "stale_after": "2026-04-01T00:00:00Z"}, body, note, tmp_path, today="2026-06-18")
    assert any("has passed" in w for w in past)
    future = okf.check_provenance({**base, "stale_after": "2027-04-01T00:00:00Z"}, body, note, tmp_path, today="2026-06-18")
    assert not any("has passed" in w or "decays" in w for w in future)


def test_stable_without_verified_entry_warns(tmp_path):
    warns = okf.check_provenance({"type": "schema", "title": "X", "description": "d",
                                  "sources": [{"resource": "s"}], "status": "stable"},
                                 "**Verify:** y", tmp_path / "x.md", tmp_path, today=TODAY)
    assert any("okf --promote" in w for w in warns)


def test_verified_actor_shape_is_checked(tmp_path):
    base = {"type": "schema", "title": "X", "description": "d", "sources": [{"resource": "s"}]}
    bad = okf.check_provenance({**base, "verified": [{"by": "krishna", "at": "2026-06-01T00:00:00Z"}]},
                               "**Verify:** y", tmp_path / "x.md", tmp_path, today=TODAY)
    assert any("not a spec actor" in w for w in bad)
    for actor in ("human:k", "process:backfill", "lk-backfill-memory/1.0"):
        ok = okf.check_provenance({**base, "verified": [{"by": actor, "at": "2026-06-01T00:00:00Z"}]},
                                  "**Verify:** y", tmp_path / "x.md", tmp_path, today=TODAY)
        assert not any("not a spec actor" in w for w in ok)


# ---- normalize_fm basics ----

def test_normalize_missing_type_is_error():
    new, changes, errors = okf.normalize_fm({"title": "T", "description": "d"}, {}, "x.md", today=TODAY)
    assert any("type" in e for e in errors)


def test_normalize_does_not_autostub_tags_or_generated():
    new, _, _ = okf.normalize_fm({"type": "schema", "title": "T", "description": "d"}, {}, "f.md", today=TODAY)
    assert "tags" not in new            # tags optional; no empty-stub cruft
    assert "generated" not in new       # never invent a producer/date the note didn't have


def test_normalize_missing_description_no_hook_is_error():
    new, _, errors = okf.normalize_fm({"type": "schema", "title": "T"}, {}, "f.md", today=TODAY)
    assert any("description" in e for e in errors)


# ---- reindex ----

def _bundle(tmp_path):
    write(tmp_path / "schema_a.md", v02(t="Alpha", d="aaa"))
    write(tmp_path / "crm" / "gotcha_b.md", v02(t="Beta", d="bbb").replace("type: schema", "type: gotcha"))
    return tmp_path


def test_reindex_creates_root_and_nested_and_is_idempotent(tmp_path):
    _bundle(tmp_path)
    okf.reindex(tmp_path)
    root = (tmp_path / "index.md").read_text(encoding="utf-8")
    nested = (tmp_path / "crm" / "index.md").read_text(encoding="utf-8")
    assert "## Subdirectories" in root and "crm/index.md" in root
    assert "## Notes" in root and "schema_a.md" in root
    assert "Beta" in nested and "gotcha_b.md" in nested
    assert not nested.startswith("---")                      # only the ROOT index carries okf_version
    okf.reindex(tmp_path)  # second run
    root2 = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert root2.count(okf.AUTO_SENTINEL) == 1 and root2.count("okf_version") == 1


def test_reindex_root_declares_okf_version(tmp_path):
    _bundle(tmp_path)
    okf.reindex(tmp_path)
    root = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert root.startswith('---\nokf_version: "0.2"\n---')
    assert okf.root_okf_version(tmp_path) == "0.2"
    assert okf.load_index_descriptions(tmp_path)["schema_a.md"] == "aaa"   # hooks still parse


def test_reindex_preserves_preamble_above_sentinel_and_adds_version_once(tmp_path):
    _bundle(tmp_path)
    (tmp_path / "index.md").write_text(f"# Keep me\n\nimportant prose\n\n{okf.AUTO_SENTINEL}\n", encoding="utf-8")
    okf.reindex(tmp_path)
    out = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "important prose" in out and out.count(okf.AUTO_SENTINEL) == 1
    assert out.startswith("---\nokf_version") and "# Keep me" in out
    okf.reindex(tmp_path)
    assert (tmp_path / "index.md").read_text(encoding="utf-8").count("okf_version") == 1


def test_reindex_refuses_no_sentinel_index_without_force(tmp_path):
    _bundle(tmp_path)
    (tmp_path / "index.md").write_text("# Hand made\n\n* keep this\n", encoding="utf-8")
    okf.reindex(tmp_path, force=False)
    assert "keep this" in (tmp_path / "index.md").read_text(encoding="utf-8")  # untouched
    okf.reindex(tmp_path, force=True)
    assert okf.AUTO_SENTINEL in (tmp_path / "index.md").read_text(encoding="utf-8")


# ---- provenance & links ----

def test_check_provenance_flags_missing_sources_and_verify_and_deprecated(tmp_path):
    warns = okf.check_provenance({"status": "deprecated"}, "body no verify here", tmp_path / "x.md", tmp_path, today=TODAY)
    joined = " ".join(warns)
    assert "sources" in joined and "Verify" in joined and "deprecated" in joined


def _archived_transcript(tmp_path, name="c6d186e7.jsonl"):
    raw = tmp_path / "ai" / "session" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / name).write_text('{"type":"user"}\n', encoding="utf-8")
    return f"ai/session/raw/{name}"


def test_check_provenance_clean_when_ok(tmp_path):
    src = _archived_transcript(tmp_path)
    warns = okf.check_provenance({"sources": [{"resource": src}], "status": "draft"},
                                 "**Verify:** run it", tmp_path / "x.md", tmp_path, today=TODAY)
    assert warns == []


def test_check_provenance_reads_legacy_source_too(tmp_path):
    src = _archived_transcript(tmp_path)
    warns = okf.check_provenance({"source": src}, "**Verify:** run it", tmp_path / "x.md", tmp_path, today=TODAY)
    assert not any("missing `sources`" in w for w in warns)


def test_check_provenance_flags_prose_session_source(tmp_path):
    warns = okf.check_provenance({"sources": [{"resource": "session 2026-06-11"}]},
                                 "**Verify:** run it", tmp_path / "x.md", tmp_path, today=TODAY)
    assert any("not a resolvable path" in w for w in warns)


def test_check_provenance_flags_transcript_that_vanished(tmp_path):
    warns = okf.check_provenance({"sources": [{"resource": "ai/session/raw/pruned.jsonl"}]},
                                 "**Verify:** run it", tmp_path / "x.md", tmp_path, today=TODAY)
    assert any("path not found" in w for w in warns)


def test_check_provenance_still_skips_urls(tmp_path):
    warns = okf.check_provenance({"sources": [{"resource": "https://claude.ai/chat/abc123"}]},
                                 "**Verify:** open it", tmp_path / "x.md", tmp_path, today=TODAY)
    assert warns == []


def test_check_links_detects_broken(tmp_path):
    write(tmp_path / "schema_a.md", v02(t="A"), body="see [b](schema_missing.md)\n")
    broken = okf.check_links(tmp_path)
    assert broken and broken[0][1] == "schema_missing.md"


# ---- move ----

def test_move_rewrites_inbound_links(tmp_path):
    write(tmp_path / "schema_a.md", v02(t="A"), body="link to [b](schema_b.md)\n")
    write(tmp_path / "schema_b.md", v02(t="B"))
    okf.move_concept(tmp_path / "schema_b.md", tmp_path / "crm" / "schema_b.md", tmp_path)
    assert (tmp_path / "crm" / "schema_b.md").exists()
    assert not (tmp_path / "schema_b.md").exists()
    a = (tmp_path / "schema_a.md").read_text(encoding="utf-8")
    assert "(crm/schema_b.md)" in a


# ---- touch ----

def test_touch_bumps_generated_at_keeps_created_and_by(tmp_path):
    write(tmp_path / "schema_a.md", v02(t="A"))
    okf.touch_notes([tmp_path / "schema_a.md"], today=TODAY, actor="process:x")
    fm, _ = okf.parse_frontmatter((tmp_path / "schema_a.md").read_text(encoding="utf-8"))
    assert fm["generated"]["at"].startswith(TODAY) and fm["generated"]["by"] == "human:tester"
    assert str(fm["created"]) == "2026-01-01"


def test_touch_migrates_a_legacy_timestamp_note(tmp_path):
    write(tmp_path / "schema_a.md", "type: schema\ntitle: A\ndescription: d\ntimestamp: 2026-01-01T00:00:00Z\nsource: s")
    okf.touch_notes([tmp_path / "schema_a.md"], today=TODAY, actor="process:x")
    fm, _ = okf.parse_frontmatter((tmp_path / "schema_a.md").read_text(encoding="utf-8"))
    assert "timestamp" not in fm and fm["generated"] == {"by": "process:x", "at": f"{TODAY}T00:00:00Z"}
    assert str(fm["created"]) == "2026-01-01"


# ---- slug token / hint ----

def test_slug_token_strips_type_prefix():
    assert okf._slug_token("schema_acme-mysql-tables") == "acme"
    assert okf._slug_token("decision_lapsed-acme-pipeline") == "lapsed"


# ---- main() exit codes ----

def test_check_exit_nonzero_on_drift(tmp_path):
    write(tmp_path / "schema_a.md", "type: schema\ntitle: A\nupdated: 2026-01-01\nsource: s\ndescription: d")
    assert okf.main([str(tmp_path), "--check", "--actor", ACTOR]) == 1


def test_check_exit_zero_when_clean(tmp_path):
    write(tmp_path / "schema_a.md", v02(t="A"))
    okf.reindex(tmp_path)
    assert okf.main([str(tmp_path), "--check", "--actor", ACTOR]) == 0


def test_gate_ignores_soft_warnings_but_check_fails(tmp_path):
    # conformant frontmatter + resolvable index, but missing sources/Verify (soft warnings)
    write(tmp_path / "schema_a.md",
          "type: schema\ntitle: A\ndescription: d\ngenerated:\n  by: human:t\n  at: '2026-01-01T00:00:00Z'\ncreated: '2026-01-01'",
          body="no verify line here\n")
    okf.reindex(tmp_path)
    assert okf.main([str(tmp_path), "--gate", "--actor", ACTOR]) == 0
    assert okf.main([str(tmp_path), "--check", "--actor", ACTOR]) == 1


def test_dry_run_hints_when_root_index_lacks_okf_version(tmp_path, capsys):
    write(tmp_path / "schema_a.md", v02(t="A"))
    (tmp_path / "index.md").write_text(f"# Memory index\n\n{okf.AUTO_SENTINEL}\n", encoding="utf-8")
    okf.main([str(tmp_path), "--actor", ACTOR])
    assert "okf_version" in capsys.readouterr().out


def test_bom_is_stripped_so_frontmatter_is_seen():
    fm, body = okf.parse_frontmatter("﻿---\ntype: schema\ntitle: T\n---\n\nb\n")
    assert fm is not None and fm["type"] == "schema"


def test_read_text_returns_none_on_non_utf8(tmp_path):
    p = tmp_path / "schema_bad.md"
    p.write_bytes(b"---\ntype: schema\ntitle: \xff\xfe bad bytes\n---\nbody\n")
    assert okf._read_text(p) is None


def test_non_utf8_note_errors_without_crashing(tmp_path):
    write(tmp_path / "schema_ok.md", v02(t="Ok"))
    (tmp_path / "schema_bad.md").write_bytes(b"---\ntype: schema\ntitle: \xff\xfe\n---\nb\n")
    assert okf.main([str(tmp_path), "--actor", ACTOR]) == 1


def test_provenance_flags_yaml_coercion_trap(tmp_path):
    warns = okf.check_provenance({"description": False, "sources": [{"resource": "s"}]}, "**Verify:** x",
                                 tmp_path / "x.md", tmp_path, today=TODAY)
    assert any("description" in w and "text" in w for w in warns)


def test_move_guards(tmp_path):
    write(tmp_path / "schema_a.md", v02(t="A"))
    write(tmp_path / "schema_b.md", v02(t="B"))
    with pytest.raises(FileExistsError):
        okf.move_concept(tmp_path / "schema_a.md", tmp_path / "schema_b.md", tmp_path)
    (tmp_path / "index.md").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        okf.move_concept(tmp_path / "index.md", tmp_path / "moved.md", tmp_path)


def test_version(capsys):
    rc = okf.main(["--version"])
    out = capsys.readouterr().out
    assert rc == 0 and okf.TOOL_VERSION in out and "0.2" in out


def test_deprecated_with_resolving_successor_does_not_warn(tmp_path):
    """A decision note supersedes an open-question, which becomes deprecated + `relates <decision>`;
    that is a normal lifecycle end, not rot, so `okf --check` must stay green after it."""
    (tmp_path / "decision_x.md").write_text("---\ntype: decision\n---\nx\n", encoding="utf-8")
    note = tmp_path / "open-question_x.md"
    base = {"type": "open-question", "title": "X", "description": "d", "sources": [{"resource": "s"}],
            "status": "deprecated"}
    body = "b\n\n**Verify:** y\n"
    linked = okf.check_provenance({**base, "relations": ["relates decision_x.md"]}, body, note, tmp_path, today=TODAY)
    assert not any("deprecated" in w for w in linked)
    orphan = okf.check_provenance(base, body, note, tmp_path, today=TODAY)
    assert any("deprecated" in w for w in orphan)
    dangling = okf.check_provenance({**base, "relations": ["relates decision_missing.md"]}, body, note, tmp_path, today=TODAY)
    assert any("deprecated" in w for w in dangling)


def test_note_with_both_timestamp_and_generated_keeps_generated():
    fm = {"type": "schema", "title": "T", "description": "d", "timestamp": "2026-01-01T00:00:00Z",
          "generated": {"by": "some-tool/1.0", "at": "2026-06-01T12:00:00Z"}, "created": "2026-01-01"}
    new, changes, errors = okf.normalize_fm(fm, {}, "f.md", today=TODAY, actor=ACTOR)
    assert "timestamp" not in new and new["generated"] == {"by": "some-tool/1.0", "at": "2026-06-01T12:00:00Z"}
    assert any("canonical" in c for c in changes) and not errors
