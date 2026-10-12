---
name: lk-audit-knowledge
version: 1.0.0
description: >
  Audit an in-repo OKF knowledge bundle (ai/memory) for notes that should not be there: machine
  bursts filed in one go from one source, low-information shards, near-duplicates, stale or
  deprecated-but-still-linked notes, drafts never promoted, orphans, and one type swamping the
  bundle. Writes an editable triage plan (keep / delete / deprecate / merge-into / promote) that
  the agent judges note by note and a human approves before anything is applied. USE WHEN:
  "audit knowledge", "audit the memory", "clean up ai/memory", "too many notes", "which notes are
  garbage", "/lk-audit-knowledge", after a build campaign filed many notes, or before promoting a
  backfill.
---

# lk-audit-knowledge: find the notes that should not be there

The rest of the knowledge system checks that notes are **well-formed**: frontmatter keys, a
source, a `**Verify:**` line, links that resolve. None of it asks whether a note **should exist**.
That gap is real and measured. One project's `ai/memory/` reached 135 notes in a day, and 118 of
them were junk auto-filed from six build reports in one run: all `type: pattern`, all created the
same day, each citing one of the six reports, each body one paragraph copied from that report plus
two lines of boilerplate, titles starting with `**`. `okf --check` passed every one of them,
because they were well-formed garbage. A reader opening `index.md` saw 118 lines of noise around 17 real notes.

`audit_knowledge.py` is the missing check. It is a **heuristic engine**: it surfaces candidates
and suggests an action for each. It never decides. The agent judges every finding, a human approves
the plan, and only then does `--apply` touch a file.

## Every verb

| Verb | Does |
|---|---|
| `audit_knowledge.py [BUNDLE]` | Read-only report, grouped by finding kind, each finding naming its notes with a one-line reason, then a `summary:` line. Exit 0 whatever it finds. `BUNDLE` defaults to `ai/memory`. |
| `audit_knowledge.py BUNDLE --json` | The same findings, the suggested plan rows and the summary as JSON, for the agent. |
| `audit_knowledge.py BUNDLE --plan OUT.md` | Write an editable triage plan: a markdown table, one row per flagged note, `action \| path \| reason`, each action pre-filled with a suggestion. Refuses to write inside the bundle (the plan would be read as a note). |
| `audit_knowledge.py BUNDLE --apply PLAN.md` | Execute an approved plan. `delete`: `git rm -q` inside a git repo, else (or if git refuses) move to `<bundle-parent>/.okf-backups/audit-<date>/`. `deprecate`: set `status: deprecated`, editing that one frontmatter line so every other key, its order, quoting and the file's line endings stay as they were. `promote`: printed, never done here; it prints one `ai/scripts/okf --promote ...` command for a human. `merge-into:<path>`: printed as a pair to merge by hand; file contents are never combined by the tool. `keep`: nothing. Ends with `now run: ai/scripts/okf --reindex && ai/scripts/okf --check`. |

`--apply` checks the whole plan before touching anything. One bad row (a path outside the bundle,
`index.md`/`log.md`, a path inside `.okf-backups`, an unknown action, a merge into itself, or a plan
written for a different bundle) refuses the entire plan with exit 2, naming every problem. A
suspicious plan is a reason to stop, not to apply the rows that look fine. Re-running an applied
plan is safe: a note already gone is reported and skipped. Exit 1 means a row failed at apply time
(for example a `deprecate` whose frontmatter could not be edited cleanly).

The script reads both frontmatter vocabularies, because bundles will be mid-migration: legacy
(`source`, `timestamp`, `status: unverified | verified | stale | open | closed`) and OKF v0.2
(`sources: [{resource}]`, `generated: {by, at}`, `status: draft | stable | deprecated`, `verified`,
`stale_after`). Legacy statuses are read through the v0.2 table (`unverified`/`open` = draft,
`verified` = stable, `stale`/`closed` = deprecated). A note whose YAML does not parse is skipped and
listed under `MALFORMED`, never a crash. `index.md`, `log.md` and anything under `.okf-backups` are
never treated as notes.

## The heuristics

Every threshold is a named constant at the top of `audit_knowledge.py`.

| Kind | Fires when | Suggested action |
|---|---|---|
| `BURST` | 5 or more notes of the **same type**, citing the **same first source**, filed on the **same day** (`created`, else `generated.at`, else `timestamp`). The source is compared by its leading path, so `ai/x.md §2 (Codex r2)` and `ai/x.md` are one source. | `delete` for a member that is also `LOW_INFO`. When at least half the cluster is `LOW_INFO`, `delete` for every member (the rest of a junk burst is usually junk too). Otherwise `keep`, with a note to read it against its source. |
| `LOW_INFO` | Any of: the body is under 240 characters once frontmatter, headings, the `**Verify:**` line and boilerplate lines that bulk filers stamp on every note (`BOILERPLATE_PHRASES`: "Recorded automatically", "Accepted (agent-authored", "not a human ruling", "Accepted from contract") are removed; the title starts with `**` or a backtick; the title and description open with the same 60 characters (the whole title if it is shorter, but at least 20) and the body adds under 80 characters beyond the description. | `keep` with "expand it or delete it" on its own; `delete` when it is part of a burst. |
| `NEAR_DUP` | Two notes whose salient terms have Jaccard similarity of 0.6 or more and share at least 3 terms. Salient terms are the title, description and slug (with its `type_` prefix removed), lowercased, minus stop-words and minus terms found in more than 40% of the bundle, the same recipe as `okf --suggest-links`. Pairs already joined by a typed relation (other than `duplicates`) were judged distinct by someone and are skipped. | The newer note: `merge-into:<older>`. The older (by `created`, then `generated.at`): `keep`. |
| `STALE` | `stale_after` is in the past; or legacy `status: stale`; or a deprecated note (v0.2 `deprecated`, legacy `stale` or `closed`) is still linked from another note. A link from the note that `supersedes` it, `duplicates` it or `contradicts` it is history, not a live dependency, and does not count. | `deprecate` for a passed `stale_after` or legacy `stale`. `keep` for a deprecated note that is still linked: the fix is in the notes that link to it, which the reason names. |
| `NEVER_PROMOTED` | `status: draft` (or legacy `unverified`/`open`) filed more than 30 days ago. | `promote` (meaning: check it, then a human promotes it or it is deleted). An `open-question` gets `keep` instead: it is an undecided fork, and promoting it settles nothing. Answer it with a decision note that `supersedes` it, then deprecate the question (the `supersedes` link keeps it out of `STALE`). |
| `ORPHAN` | No markdown link or `relations` entry from any other note points at it. `index.md` does not count. | `keep`. A weak signal: plenty of good notes are orphans. The plan lists orphan-only notes in a separate section. |
| `OVERSIZED_TYPE` | One `type` is more than 60% of a bundle of 20 or more notes. | None. A bundle hint, usually the shadow of a `BURST`. |

When a note trips several heuristics, the plan row carries every reason and the strongest action
(delete, then merge-into, deprecate, promote, keep).

## The audit workflow (mandatory: read this before running `--apply`)

The heuristics are recall-favouring and blind to meaning. A `BURST` can be a legitimate backfill
of schema notes from one database; a short `LOW_INFO` note can be a perfectly good one-line gotcha;
two `NEAR_DUP` notes can be a rule and its exception. **The heuristic engine proposes; the agent
judges each item; the human approves; only then is the plan applied.** Every step below is
mandatory.

1. **Run the report.** `python ~/.claude/skills/lk-audit-knowledge/audit_knowledge.py ai/memory`
   (or `--json`). Read the summary line first, then each section.
2. **The agent judges every finding, then writes the plan.** Run `--plan` to a file outside the
   bundle (`ai/scratch/audit-plan.md`, or a temp dir), then open the notes themselves:
   - For each `BURST` cluster, open the cited source and a sample of the members (all of them for a
     small cluster). If each note is a copy of a line that still lives in the source, the source is
     the record and the notes are surplus: `delete`. If a member carries something the source does
     not (a correction, a later finding, a cross-reference), change its row to `keep`.
   - For each `NEAR_DUP` pair, read both. A true duplicate stays `merge-into`; a rule and its
     refinement are not duplicates: change both rows to `keep`, and consider a `refines` relation.
   - For each `LOW_INFO` note outside a burst, decide whether it is terse-but-true (`keep`),
     worth expanding now (`keep`, then expand it), or empty (`delete`).
   - For `STALE` and `NEVER_PROMOTED`, check the claim against the code or source before
     choosing `deprecate`, `promote` or `delete`.
   Never pass a suggestion through without reading the note. An unread `delete` is the failure
   this workflow exists to prevent.
3. **A human approves the plan before `--apply`.** Show the human the edited plan (the
   `## Suggested actions` table and the summary of what changed from the suggestions) and wait for
   an explicit yes. An agent does not delete notes on its own authority. They are git-tracked and
   recoverable, but a silent mass deletion is still a decision that belongs to the owner of the
   knowledge. A question that goes unanswered is not a yes.
4. **Apply, then reindex and check.** `audit_knowledge.py ai/memory --apply <plan>`, then
   `ai/scripts/okf --reindex && ai/scripts/okf --check`. If the plan had `promote` rows, the apply
   output prints the `ai/scripts/okf --promote ...` command for the human to run. Commit the result
   as one change ("Memory audit: ..."), so the deletion is reviewable and revertible in one place.
5. **Do the merges by hand.** For each `merge-into` pair the apply step printed: open both notes,
   fold anything the newer one says that the older does not into the older (keeping its
   `**Verify:**` line true), add the newer note's sources to the older's `sources`, then delete
   the newer note (`git rm`) and repoint any links to it (`ai/scripts/okf --check` lists the
   broken ones). The tool never combines file contents, because deciding which sentence survives
   is a judgement.

## Where machine bursts come from

Any automation that files many notes from one source in one run leaves the same shape: an agent
dumping a report into notes one paragraph at a time, a backfill campaign that skipped its per-run
cap, a hook that files a note for every item of whatever it just processed. The tool varies; the
shape does not. Every member has one `type`, cites one source and carries one filing date, and its
body is mostly a paragraph copied from that source plus the filer's fixed boilerplate. `BURST` keys
on that shape and names no tool, so it catches the next filer as well as the last one. Such shards
show up as one `BURST` cluster per source, nearly every member also `LOW_INFO`. Deleting them
usually loses nothing, because the source they were copied from is still in the repo and stays the
record; step 2 of the workflow is where the agent confirms that before choosing `delete`.

## Measured

On that project's bundle as it stood before its own clean-up (135 notes: 118 shards auto-filed
from six build reports in one day, and 17 real notes): `BURST` found 6 clusters totalling exactly
the 118 shards, `LOW_INFO` 110 of them, and the plan suggested `delete` for exactly those 118 and
nothing else. No real note received any finding
except `ORPHAN` (9 of 17, a weak signal by design). Counting a burst by source and day alone
wrongly flags 7 of the 17 real notes: a session distilled by hand into a
decision, gotchas, runbooks and a reference, all citing one transcript. That is `lk-end-session`
working as designed, which is why `type` is part of the burst key.

## Install

Copied with the other `lk-*` skills into `~/.claude/skills/` (see the repo README). There is no
project shim: run it from the project root as
`python ~/.claude/skills/lk-audit-knowledge/audit_knowledge.py ai/memory`. `pyyaml` is the only
runtime dependency. It is self-contained (it does not import `okf_normalize.py`), so it runs even
where `lk-init-ai-workspace` is a different version.

Run its tests (needs `pip install pytest`):

```bash
cd ~/.claude/skills/lk-audit-knowledge && python -m pytest -q
```

## Limitations

- **Mixed-type machine bursts split.** A tool that writes several types from one source in one run
  becomes one cluster per type, and a type with fewer than 5 notes is not reported as a burst.
- **Similarity is lexical.** `NEAR_DUP` compares titles, descriptions and slugs, not bodies. Two
  notes that say the same thing in different words are missed; two notes that share vocabulary but
  disagree are flagged. Step 2 of the workflow is what catches both.
- **Dates come from frontmatter.** A note with no `created`, `generated.at` or `timestamp` is never
  part of a burst and never counts as an old draft.
