"""Tests for okf_normalize.py. Run: pytest test_okf_normalize.py -q  (deps: pytest, pyyaml)."""
from pathlib import Path

import okf_normalize as okf

TODAY = "2026-06-17"


def write(p: Path, fm_lines: str, body: str = "body\n\n**Verify:** run x\n"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\n{fm_lines}\n---\n\n{body}", encoding="utf-8")


# ---- frontmatter round-trip ----

def test_parse_roundtrip_preserves_body_and_orders_keys():
    text = "---\nstatus: verified\ntype: schema\ntitle: T\n---\n\nhello\n"
    fm, body = okf.parse_frontmatter(text)
    assert fm["type"] == "schema" and body.strip() == "hello"
    out = okf.serialize(fm, body)
    # type comes before status per KEY_ORDER, regardless of input order
    assert out.index("type:") < out.index("status:")
    fm2, body2 = okf.parse_frontmatter(out)
    assert fm2 == fm and body2.strip() == "hello"


def test_parse_no_frontmatter_returns_none():
    fm, body = okf.parse_frontmatter("# just a heading\n")
    assert fm is None


def test_parse_malformed_yaml_does_not_raise():
    # unquoted source value with a colon — invalid YAML; must NOT crash, returns None
    bad = "---\ntype: pattern\nsource: session 2026-06-12 (Sam: left/right diverge)\n---\n\nbody\n"
    fm, body = okf.parse_frontmatter(bad)   # would raise yaml.YAMLError before the fix
    assert fm is None


def test_malformed_note_does_not_crash_run_and_others_still_processed(tmp_path):
    write(tmp_path / "schema_good.md", "type: schema\ntitle: Good\ndescription: d\ntimestamp: 2026-01-01T00:00:00Z\ncreated: 2026-01-01\nsource: s")
    (tmp_path / "pattern_bad.md").write_text(
        "---\ntype: pattern\nsource: session (Sam: left/right)\n---\n\nb\n", encoding="utf-8")
    rc = okf.main([str(tmp_path)])          # bare run — must complete, not crash
    assert rc == 1                          # the malformed note is an error -> nonzero
    # the good note was still reachable (no crash mid-iteration); reindex sees it
    okf.reindex(tmp_path)
    assert "schema_good.md" in (tmp_path / "index.md").read_text(encoding="utf-8")


def test_reference_is_a_valid_type():
    assert "reference" in okf.TYPE_ENUM
    # normalize_fm should not flag a reference note's type, and the filename check accepts reference_
    new, changes, errors = okf.normalize_fm(
        {"type": "reference", "title": "T", "description": "d"}, {}, "reference_x.md", today=TODAY)
    assert not any("outside our enum" in c for c in changes)
    assert okf._slug_token("reference_pipeline-tools") == "pipeline"  # reference_ prefix stripped


# ---- review (promotion queue) ----

def test_review_lists_only_unverified(tmp_path):
    base = "type: schema\ntitle: {t}\ndescription: d\ntimestamp: 2026-01-01T00:00:00Z\ncreated: 2026-01-01\nsource: s\nstatus: {s}"
    write(tmp_path / "schema_a.md", base.format(t="A", s="unverified"))
    write(tmp_path / "schema_b.md", base.format(t="B", s="verified"))
    write(tmp_path / "sub" / "schema_c.md", base.format(t="C", s="unverified"))  # nested counts
    rows = okf.review_unverified(tmp_path)
    assert {p.name for p, _ in rows} == {"schema_a.md", "schema_c.md"}  # excludes the verified note
    assert okf.main([str(tmp_path), "--review"]) == 0                   # read-only, exits 0


# ---- suggest-links (v0.7) ----

def test_suggest_links_surfaces_unlinked_pair_and_excludes_linked(tmp_path):
    base = "type: schema\ntitle: {t}\ndescription: {d}\nsource: s\nstatus: unverified"
    # two notes share the salient term "invoice" but are NOT linked -> should surface
    write(tmp_path / "schema_invoice_api.md", base.format(t="Invoice API", d="invoice payment fields"))
    write(tmp_path / "schema_invoice_db.md", base.format(t="Invoice DB", d="invoice payment table"))
    # an unrelated note shares nothing salient
    write(tmp_path / "schema_widget.md", base.format(t="Widget", d="ui widget toggle"))
    pairs = okf.suggest_links(tmp_path, min_score=1)
    names = {frozenset({pa.name, pb.name}) for _s, pa, pb, _sh in pairs}
    assert frozenset({"schema_invoice_api.md", "schema_invoice_db.md"}) in names
    # now link them with a typed relation -> the pair must drop out
    text = (tmp_path / "schema_invoice_api.md").read_text(encoding="utf-8")
    (tmp_path / "schema_invoice_api.md").write_text(
        text.replace("status: unverified",
                     "status: unverified\nrelations:\n  - relates schema_invoice_db.md"), encoding="utf-8")
    pairs2 = okf.suggest_links(tmp_path, min_score=1)
    names2 = {frozenset({pa.name, pb.name}) for _s, pa, pb, _sh in pairs2}
    assert frozenset({"schema_invoice_api.md", "schema_invoice_db.md"}) not in names2
    assert okf.main([str(tmp_path), "--suggest-links"]) == 0   # read-only, exits 0


# ---- agent-memory adoptions (v0.6): workaround type, typed relations, decay ----

def test_workaround_is_a_valid_type():
    assert "workaround" in okf.TYPE_ENUM
    new, changes, errors = okf.normalize_fm(
        {"type": "workaround", "title": "T", "description": "d"}, {}, "workaround_x.md", today=TODAY)
    assert not any("outside our enum" in c for c in changes)


def test_relations_typed_and_validated(tmp_path):
    (tmp_path / "schema_target.md").write_text("---\ntype: schema\n---\nx\n", encoding="utf-8")
    note = tmp_path / "decision_x.md"
    base = {"type": "decision", "title": "X", "description": "d", "source": "s"}
    body = "b\n\n**Verify:** y\n"
    ok = okf.check_provenance({**base, "relations": ["supersedes schema_target.md"]}, body, note, tmp_path, today=TODAY)
    assert not any("relation" in w for w in ok)                       # valid verb + resolving target
    bad_verb = okf.check_provenance({**base, "relations": ["frobnicates schema_target.md"]}, body, note, tmp_path, today=TODAY)
    assert any("verb in" in w for w in bad_verb)
    broken = okf.check_provenance({**base, "relations": ["supersedes missing.md"]}, body, note, tmp_path, today=TODAY)
    assert any("relation target not found" in w for w in broken)


def test_verified_on_decay_warns(tmp_path):
    note = tmp_path / "schema_x.md"
    base = {"type": "schema", "title": "X", "description": "d", "source": "s", "status": "verified"}
    body = "b\n\n**Verify:** y\n"
    old = okf.check_provenance({**base, "verified_on": "2026-01-01"}, body, note, tmp_path, today="2026-06-18")
    assert any("decays" in w for w in old)                            # >90d -> decay warning
    fresh = okf.check_provenance({**base, "verified_on": "2026-06-17"}, body, note, tmp_path, today="2026-06-18")
    assert not any("decays" in w for w in fresh)                      # recent -> no warning


# ---- normalize_fm ----

def test_normalize_updated_to_timestamp_and_created_and_description():
    fm = {"type": "schema", "title": "T", "updated": "2026-06-11"}
    desc = {"schema_x.md": "the hook"}
    new, changes, errors = okf.normalize_fm(fm, desc, "schema_x.md", today=TODAY)
    assert new["timestamp"] == "2026-06-11T00:00:00Z"
    assert "updated" not in new
    assert new["created"] == "2026-06-11"          # backfilled from timestamp, set-once
    assert new["description"] == "the hook"
    assert not errors


def test_normalize_drops_redundant_updated_when_timestamp_present():
    fm = {"type": "schema", "title": "T", "description": "d",
          "timestamp": "2026-06-11T00:00:00Z", "updated": "2026-06-15", "created": "2026-06-11"}
    new, changes, errors = okf.normalize_fm(fm, {}, "f.md", today=TODAY)
    assert "updated" not in new and new["timestamp"] == "2026-06-11T00:00:00Z"
    assert any("updated" in c for c in changes)


def test_normalize_missing_type_is_error():
    new, changes, errors = okf.normalize_fm({"title": "T", "description": "d"}, {}, "x.md", today=TODAY)
    assert any("type" in e for e in errors)


def test_normalize_does_not_autostub_tags():
    new, _, _ = okf.normalize_fm({"type": "schema", "title": "T", "description": "d"}, {}, "f.md", today=TODAY)
    assert "tags" not in new            # tags optional now; no empty-stub cruft


def test_normalize_missing_description_no_hook_is_error():
    new, _, errors = okf.normalize_fm({"type": "schema", "title": "T"}, {}, "f.md", today=TODAY)
    assert any("description" in e for e in errors)


# ---- reindex ----

def _bundle(tmp_path):
    write(tmp_path / "schema_a.md", "type: schema\ntitle: Alpha\ndescription: aaa\ntimestamp: 2026-01-01T00:00:00Z\nsource: s")
    write(tmp_path / "crm" / "gotcha_b.md", "type: gotcha\ntitle: Beta\ndescription: bbb\ntimestamp: 2026-01-01T00:00:00Z\nsource: s")
    return tmp_path


def test_reindex_creates_root_and_nested_and_is_idempotent(tmp_path):
    _bundle(tmp_path)
    okf.reindex(tmp_path)
    root = (tmp_path / "index.md").read_text(encoding="utf-8")
    nested = (tmp_path / "crm" / "index.md").read_text(encoding="utf-8")
    assert "## Subdirectories" in root and "crm/index.md" in root
    assert "## Notes" in root and "schema_a.md" in root
    assert "Beta" in nested and "gotcha_b.md" in nested
    okf.reindex(tmp_path)  # second run
    assert (tmp_path / "index.md").read_text(encoding="utf-8").count(okf.AUTO_SENTINEL) == 1


def test_reindex_preserves_preamble_above_sentinel(tmp_path):
    _bundle(tmp_path)
    (tmp_path / "index.md").write_text(f"# Keep me\n\nimportant prose\n\n{okf.AUTO_SENTINEL}\n", encoding="utf-8")
    okf.reindex(tmp_path)
    out = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "important prose" in out and out.count(okf.AUTO_SENTINEL) == 1


def test_reindex_refuses_no_sentinel_index_without_force(tmp_path):
    _bundle(tmp_path)
    (tmp_path / "index.md").write_text("# Hand made\n\n* keep this\n", encoding="utf-8")
    okf.reindex(tmp_path, force=False)
    assert "keep this" in (tmp_path / "index.md").read_text(encoding="utf-8")  # untouched
    okf.reindex(tmp_path, force=True)
    assert okf.AUTO_SENTINEL in (tmp_path / "index.md").read_text(encoding="utf-8")


# ---- provenance & links ----

def test_check_provenance_flags_missing_source_and_verify_and_stale(tmp_path):
    warns = okf.check_provenance({"status": "stale"}, "body no verify here", tmp_path / "x.md", tmp_path, today=TODAY)
    joined = " ".join(warns)
    assert "source" in joined and "Verify" in joined and "stale" in joined


def test_check_provenance_clean_when_ok(tmp_path):
    warns = okf.check_provenance({"source": "session 2026-06-11", "status": "verified"},
                                 "**Verify:** run it", tmp_path / "x.md", tmp_path, today=TODAY)
    assert warns == []


def test_check_links_detects_broken(tmp_path):
    write(tmp_path / "schema_a.md", "type: schema\ntitle: A\ndescription: d\nsource: s",
          body="see [b](schema_missing.md)\n")
    broken = okf.check_links(tmp_path)
    assert broken and broken[0][1] == "schema_missing.md"


# ---- move ----

def test_move_rewrites_inbound_links(tmp_path):
    write(tmp_path / "schema_a.md", "type: schema\ntitle: A\ndescription: d\nsource: s",
          body="link to [b](schema_b.md)\n")
    write(tmp_path / "schema_b.md", "type: schema\ntitle: B\ndescription: d\nsource: s")
    okf.move_concept(tmp_path / "schema_b.md", tmp_path / "crm" / "schema_b.md", tmp_path)
    assert (tmp_path / "crm" / "schema_b.md").exists()
    assert not (tmp_path / "schema_b.md").exists()
    a = (tmp_path / "schema_a.md").read_text(encoding="utf-8")
    assert "(crm/schema_b.md)" in a    # link rewritten to the new location


# ---- touch ----

def test_touch_bumps_timestamp_keeps_created(tmp_path):
    write(tmp_path / "schema_a.md", "type: schema\ntitle: A\ndescription: d\ntimestamp: 2026-01-01T00:00:00Z\ncreated: 2026-01-01\nsource: s")
    okf.touch_notes([tmp_path / "schema_a.md"], today=TODAY)
    fm, _ = okf.parse_frontmatter((tmp_path / "schema_a.md").read_text(encoding="utf-8"))
    assert fm["timestamp"].startswith(TODAY) and str(fm["created"]) == "2026-01-01"


# ---- slug token / hint ----

def test_slug_token_strips_type_prefix():
    assert okf._slug_token("schema_acme-mysql-tables") == "acme"
    assert okf._slug_token("decision_lapsed-acme-pipeline") == "lapsed"  # honest token accident


# ---- main() exit codes ----

def test_check_exit_nonzero_on_drift(tmp_path):
    write(tmp_path / "schema_a.md", "type: schema\ntitle: A\nupdated: 2026-01-01\nsource: s\ndescription: d")
    rc = okf.main([str(tmp_path), "--check"])
    assert rc == 1            # `updated` is drift -> strict check fails


def test_check_exit_zero_when_clean(tmp_path):
    write(tmp_path / "schema_a.md",
          "type: schema\ntitle: A\ndescription: d\ntimestamp: 2026-01-01T00:00:00Z\ncreated: 2026-01-01\nsource: s")
    okf.reindex(tmp_path)
    rc = okf.main([str(tmp_path), "--check"])
    assert rc == 0


def test_gate_ignores_soft_warnings_but_check_fails(tmp_path):
    # conformant frontmatter + resolvable index, but missing source/Verify (soft warnings)
    write(tmp_path / "schema_a.md",
          "type: schema\ntitle: A\ndescription: d\ntimestamp: 2026-01-01T00:00:00Z\ncreated: 2026-01-01",
          body="no verify line here\n")
    okf.reindex(tmp_path)
    assert okf.main([str(tmp_path), "--gate"]) == 0    # no mechanical drift
    assert okf.main([str(tmp_path), "--check"]) == 1    # soft provenance warnings fail strict


def test_bom_is_stripped_so_frontmatter_is_seen():
    fm, body = okf.parse_frontmatter("﻿---\ntype: schema\ntitle: T\n---\n\nb\n")
    assert fm is not None and fm["type"] == "schema"


def test_read_text_returns_none_on_non_utf8(tmp_path):
    p = tmp_path / "schema_bad.md"
    p.write_bytes(b"---\ntype: schema\ntitle: \xff\xfe bad bytes\n---\nbody\n")  # invalid UTF-8
    assert okf._read_text(p) is None


def test_non_utf8_note_errors_without_crashing(tmp_path):
    write(tmp_path / "schema_ok.md", "type: schema\ntitle: Ok\ndescription: d\ntimestamp: 2026-01-01T00:00:00Z\ncreated: 2026-01-01\nsource: s")
    (tmp_path / "schema_bad.md").write_bytes(b"---\ntype: schema\ntitle: \xff\xfe\n---\nb\n")
    rc = okf.main([str(tmp_path)])      # must not raise UnicodeDecodeError
    assert rc == 1                       # the bad file is an [ERROR]


def test_provenance_flags_yaml_coercion_trap(tmp_path):
    # `description: no` (unquoted) parses as bool False -> must be flagged, not silently shipped
    warns = okf.check_provenance({"description": False, "source": "s"}, "**Verify:** x",
                                 tmp_path / "x.md", tmp_path, today=TODAY)
    assert any("description" in w and "text" in w for w in warns)


def test_move_guards(tmp_path):
    write(tmp_path / "schema_a.md", "type: schema\ntitle: A\ndescription: d\nsource: s")
    write(tmp_path / "schema_b.md", "type: schema\ntitle: B\ndescription: d\nsource: s")
    import pytest
    with pytest.raises(FileExistsError):              # DST already exists
        okf.move_concept(tmp_path / "schema_a.md", tmp_path / "schema_b.md", tmp_path)
    (tmp_path / "index.md").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):                   # refuse to move a reserved file
        okf.move_concept(tmp_path / "index.md", tmp_path / "moved.md", tmp_path)


def test_version(capsys):
    rc = okf.main(["--version"])
    out = capsys.readouterr().out
    assert rc == 0 and okf.TOOL_VERSION in out
