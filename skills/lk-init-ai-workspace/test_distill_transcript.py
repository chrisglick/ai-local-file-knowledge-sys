"""Tests for distill_transcript.py — the citable session record.

The tests that matter here are the exclusion ones. A distiller that leaks tool output is worse
than no distiller, because the output gets committed on the strength of it.
"""
import json

import distill_transcript as dt


def line(role, content, **kw):
    d = {"type": role, "message": {"role": role, "content": content}, "timestamp": "2026-07-15T11:57:00Z"}
    d.update(kw)
    return json.dumps(d)


# ---- the load-bearing exclusion ----

def test_tool_result_is_excluded_despite_having_user_role():
    """A tool_result block carries role == "user". Filtering by role instead of block type would
    archive every command's output — env dumps, file reads, stdout. This is the whole safety model."""
    raw = [
        line("user", "what env vars are set?"),
        line("user", [{"type": "tool_result", "content": "AWS_SECRET_ACCESS_KEY=hunter2\nPAI_DIR=C:\\x"}]),
        line("assistant", [{"type": "text", "text": "Checked."}]),
    ]
    turns = dt.extract_turns(raw)
    blob = " ".join(t["text"] for t in turns)
    assert "hunter2" not in blob
    assert "AWS_SECRET_ACCESS_KEY" not in blob
    assert [t["role"] for t in turns] == ["user", "assistant"]


def test_tool_use_and_thinking_are_excluded():
    raw = [line("assistant", [
        {"type": "thinking", "thinking": "internal reasoning nobody should cite"},
        {"type": "tool_use", "name": "Bash", "input": {"command": "curl -H 'Authorization: Bearer abc123'"}},
        {"type": "text", "text": "Done."},
    ])]
    turns = dt.extract_turns(raw)
    assert len(turns) == 1
    assert turns[0]["text"] == "Done."


def test_toplevel_tooluseresult_is_excluded():
    raw = [line("user", "go", toolUseResult={"stdout": "GITHUB_TOKEN=ghp_" + "a" * 36})]
    turns = dt.extract_turns(raw)
    assert turns == [{"role": "user", "text": "go", "ts": "2026-07-15T11:57:00Z"}]


def test_sidechain_subagent_turns_excluded():
    raw = [line("assistant", [{"type": "text", "text": "subagent chatter"}], isSidechain=True),
           line("assistant", [{"type": "text", "text": "real answer"}])]
    assert [t["text"] for t in dt.extract_turns(raw)] == ["real answer"]


# ---- prose extraction ----

def test_keeps_human_and_assistant_prose_in_order():
    raw = [line("user", "do the thing"), line("assistant", [{"type": "text", "text": "done, here is why"}])]
    turns = dt.extract_turns(raw)
    assert [(t["role"], t["text"]) for t in turns] == [
        ("user", "do the thing"), ("assistant", "done, here is why")]


def test_strips_injected_harness_blocks():
    raw = [line("user", "real question<system-reminder>injected noise</system-reminder>")]
    assert dt.extract_turns(raw)[0]["text"] == "real question"


def test_skips_malformed_and_empty_lines():
    assert dt.extract_turns(["", "not json{{{", line("user", "survivor")]) == [
        {"role": "user", "text": "survivor", "ts": "2026-07-15T11:57:00Z"}]


# ---- secret scan: precision, and honest about recall ----

def test_scan_finds_issuer_formatted_tokens():
    found = dict((l, m) for l, m in dt.scan_secrets(
        "tok ghp_" + "a" * 36 + " and AKIA" + "B" * 16 + " and sk-ant-" + "c" * 24))
    assert "GitHub token" in found and "AWS access key id" in found and "Anthropic API key" in found


def test_scan_ignores_prose_mentioning_a_prefix():
    """Discussing `gho_` in a sentence is not a token. This exact case appeared in a real session."""
    assert dt.scan_secrets("the prefixes are `ghp_`/`gho_` and `sk-ant-`") == []


def test_scan_ignores_masked_output():
    """`gh auth status` prints gho_**** — already masked, must not be flagged as a live token."""
    assert dt.scan_secrets("Token: gho_" + "*" * 36) == []


def test_scan_does_not_flag_uuids_or_shas():
    """Transcripts are full of these; flagging them would train people to ignore the scanner."""
    assert dt.scan_secrets("session c6d186e7-3e46-4040-a121-7ee16bedf2aa commit 9a2220b" +
                           " sha " + "a1b2c3d4" * 5) == []


def test_scan_cannot_see_unstructured_secrets():
    """Documents the limit rather than pretending it away: this is why raw stays gitignored and
    why the tool never reports 'clean'."""
    assert dt.scan_secrets("db password is hunter2, host is internal-billing.corp.local") == []


def test_redact_replaces_token_and_reports_it():
    body, hits = dt.redact("key=ghp_" + "z" * 36 + " end")
    assert "ghp_" not in body and "[REDACTED: GitHub token]" in body
    assert len(hits) == 1


# ---- transcript lookup ----

def test_find_transcript_globs_by_uuid_not_cwd_mangling(tmp_path):
    """Claude Code mangles cwd into the project dir name (non-alphanumerics -> '-'), which differs
    between a Windows path and its git-bash view. The UUID is unambiguous everywhere."""
    d = tmp_path / "D--Projects--tech-ai-skills"
    d.mkdir()
    (d / "abc-123.jsonl").write_text("{}")
    assert dt.find_transcript("abc-123", tmp_path) == d / "abc-123.jsonl"
    assert dt.find_transcript("nope", tmp_path) is None


# ---- config: fails safe, because the user is not a security expert ----

def _conf(tmp_path, body):
    (tmp_path / "ai").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ai" / "okf.conf").write_text(body, encoding="utf-8")
    return tmp_path / "ai" / "okf.conf"


def test_missing_config_defaults_to_local_not_shared():
    """No config must never mean 'publish'. The safe end is the default end."""
    assert dt.read_mode(None) == "local"
    assert dt.DEFAULT_MODE == "local"


def test_reads_each_mode(tmp_path):
    for m in ("off", "local", "shared"):
        assert dt.read_mode(_conf(tmp_path, f"archive = {m}\n")) == m


def test_config_ignores_comments_and_is_case_insensitive(tmp_path):
    cfg = _conf(tmp_path, "# archive = shared\narchive = LOCAL  # trailing note\n")
    assert dt.read_mode(cfg) == "local"


def test_garbled_value_falls_back_to_safe_mode(tmp_path):
    """A typo must not silently upgrade a project to publishing its conversations."""
    assert dt.read_mode(_conf(tmp_path, "archive = shred\n")) == "local"
    assert dt.read_mode(_conf(tmp_path, "archive =\n")) == "local"
    assert dt.read_mode(_conf(tmp_path, "nonsense\n")) == "local"


def test_unreadable_config_falls_back_to_safe_mode(tmp_path):
    assert dt.read_mode(tmp_path / "ai" / "does-not-exist.conf") == "local"


def test_find_config_walks_up_from_a_subdirectory(tmp_path):
    cfg = _conf(tmp_path, "archive = off\n")
    deep = tmp_path / "src" / "nested" / "deep"
    deep.mkdir(parents=True)
    assert dt.find_config(deep) == cfg
    assert dt.read_mode(dt.find_config(deep)) == "off"


def test_render_declares_what_was_left_out(tmp_path):
    out = dt.render([{"role": "user", "text": "hi", "ts": "2026-07-15T11:57:00Z"}],
                    "abc-123", tmp_path / "abc-123.jsonl", "2026-07-15")
    assert "session: abc-123" in out
    assert "excluded: tool results" in out
    assert "not a complete record" in out
