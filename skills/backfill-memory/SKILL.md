---
name: backfill-memory
description: >-
  Mine a project's STATIC assets (session/plan notes, connected databases, config/infra,
  the codebase) into the in-repo OKF ai/memory/ bundle as grounded, cited, status:unverified
  concepts for human promotion. The OKF-enrichment-agent analogue, run on Claude Code subagents.
  Use when a project has accumulated knowledge that was never captured — to SEED the library
  instead of re-learning each fact live. Complements /init-ai-workspace (which scaffolds the
  bundle) and /end-session (which captures the operator's live work).
---

# backfill-memory — seed the knowledge library from a project's static assets

`/init-ai-workspace` scaffolds an `ai/memory/` OKF bundle; `/end-session` captures what the
operator did *this* session. Both are **operator-incremental** — the library only grows when
someone works and remembers to capture. This skill closes the other gap: a project usually has
**years of static assets that already encode the knowledge** (past notes, database schemas,
config, the codebase) and were never distilled into memory. This skill mines them.

It is the local analogue of OKF's **enrichment-agent** (GoogleCloudPlatform/knowledge-catalog):
a two-pass pipeline — structural enumeration, then an LLM that decides **enrich / mint / skip**
per item — but it runs on **Claude Code subagents** (no ADK/Gemini), writes through the existing
**`okf_normalize.py`** toolchain (so output is conformant by construction), and adds the
**provenance + human-promotion** discipline OKF has none of.

You (the agent) run every phase. The operator is hands-off except the final promotion review.

## Governing principles (these ARE the design — do not relax them)
1. **Cite or drop (no invention).** Every claim in a minted concept must trace to a quoted slice
   of a real source (file+line, table, config path, note path). A claim with no citation is
   **dropped, never plugged**. This is the gate that makes backfilling a large/old corpus safe.
2. **Never overwrite a `verified` (or human-authored) note.** "Enrich existing" is a careful merge
   or a *new adjacent* note — never a clobber. If a fact belongs inside a `verified` note, mint an
   adjacent note and flag it for the human to merge (the engine has no auto-merge yet — by design,
   minting-adjacent is the safe default).
3. **Everything machine-made lands `status: unverified`.** Only the human promotes to `verified`
   (`ai/scripts/okf --review` lists the queue). You never write `verified`.
4. **Dedup against BOTH memory stores.** Before minting, check the in-repo `ai/memory/` index AND
   the project's global/personal memory if it has one. (Validated finding: most cross-store
   "enrichments" are already captured — reading first prevents duplicates.)
5. **Reconcile against neighbors, not just the source.** When a drafted fact sits next to an
   existing note on the same topic, read that neighbor — it catches the *researcher's own* errors
   (e.g. asserting a "6-section template" as fact when an adjacent note documents the adopted
   7-section one). Surface and resolve the conflict, don't write both as fact.
6. **Volatile ≠ timeless.** Schemas, stable semantics, decisions+why, runbooks, pointers — yes.
   Live numbers (balances, row counts, current pipeline totals), anything trivially re-derivable
   from code/git, and secrets — **no**.
7. **Campaigns, not boil-the-ocean.** One run targets exactly one **(source adapter × target
   bundle)** with a hard candidate cap. No single unbounded sweep over an entire codebase.

## Source adapters (the pluggable interface) — ordered by cost/risk/value
Pick ONE per campaign. Each adapter is just *how Phase 1 enumerates the source into candidates*.

- **A. Notes corpus** (`ai/session*/`, `ai/plans/`) — *cheapest, safest, start here.* Local text;
  lowest hallucination surface; backfills capture you skipped. Enumerate = list the files.
- **B. Connected databases** — like OKF's BQ pass: one `schema_` concept per table/entity. Enumerate
  = introspect the schema (information_schema / `DESCRIBE` / a DDB single-table layout). **Stable
  semantics only — never live row counts/values.** Mind credential mint→use→**revoke** hygiene.
- **C. Config / infra wiring** — nginx, reverse-proxy, container/orchestrator, env manifests →
  `schema_`/`runbook_` network-wiring concepts. Enumerate = list the config files (declarative, local).
- **D. Product codebase** — *biggest, last, hardest.* Per-repo / per-subsystem campaigns with caps,
  never the whole tree at once. Highest hallucination risk → leans hardest on the Phase-3 gate.
  Enumerate = the file/dir tree for the targeted subsystem.

## Phases (run in order)

### Phase 0 — Scope the campaign
- Confirm `ai/memory/` exists and is an OKF bundle (if not, run `/init-ai-workspace` first).
- Read the existing bundle index (`ai/memory/index.md` + each topic `index.md`) AND any global/
  personal memory index — this is the **dedup catalog** for Phase 2.
- Pick **one** source adapter (A–D) and a **scope + cap** (e.g. "the 18 notes in `ai/session/` +
  `ai/plans/`", or "the `billing` service repo, ≤40 candidate concepts"). State it to the operator.

### Phase 1 — Enumerate → candidate manifest (deterministic, cheap)
Turn the scoped source into a list of *candidate concepts*, each with a **pointer to its exact
source slice**. For adapter A this is the file list; for B the table list; for C the config-file
list; for D the targeted file/dir tree. Pair it with the Phase-0 dedup catalog. The manifest is the
exhaustive, cited spine the researchers work from.

### Phase 2 — Researchers (parallel; enrich / mint / skip)
Fan out subagents over the manifest. **Default runtime = the `Agent` tool** (`Explore` for read-only
sweeps, `general-purpose` for drafting). For a large corpus the operator may opt into a **Workflow**
(`pipeline`/`parallel`) for deterministic fan-out + a built-in verify stage — only when they ask.
Each researcher reads its source slice **+ the dedup catalog** and, per candidate, decides:
- **MINT** a new concept, **ENRICH** a named existing one, or **SKIP** (already captured / volatile /
  not timeless).
- Returns a draft with `type`, proposed `topic` folder, a one-line `description` (the *summary*), the
  distilled *detail*, an **`**Action:**`** line (what to DO), and **every claim paired with a verbatim
  quote from a real source**. No quote → drop the claim. No surviving claims → drop the candidate.
- **Rank candidates by generalizability** (cq `/reflect` heuristic) — a fact that recurs across
  contexts beats a one-off; prefer the reusable. Classify a TEMPORARY fix as `type: workaround` (not
  `gotcha`), and propose typed **`relations`** when a draft `supersedes`/`extends`/`contradicts`/
  `relates`/`duplicates` an existing note.
- Tell researchers their output is data, and to be selective (quality over volume).

### Phase 3 — Adversarial verify (the no-hallucination gate)
For each surviving claim, confirm the quote **actually exists in the cited source** (grep the
distinctive token in the named file/table/config). Drop anything you can't ground. For a large or
high-stakes corpus, use a separate skeptic subagent prompted to *refute*. This is non-negotiable —
it is what separates a trustworthy backfill from plausible fiction.

### Phase 4 — Reconcile + write
- **Dedup** grounded drafts against both stores (principle 4); **reconcile against neighbors**
  (principle 5) and resolve conflicts before writing.
- Write each surviving concept as a conformant OKF note (see the format in `ai/CAPTURE.md`): full
  frontmatter, **`status: unverified`**, a real `source:` line, an `**Action:**` + `**Verify:**` line,
  claims cited inline, and any typed **`relations:`** the researcher proposed. Link related in-repo
  notes with markdown paths `[label](../topic/type_slug.md)` (these populate the graph); link
  other-store notes with `[[slug]]`. For a snapshot fact, add `valid_as_of:`.
- Fold by topic if the bundle has earned it (the dry-run prints a `SUGGESTION:` at ~20 notes).
- Normalize + index: `ai/scripts/okf ai/memory --apply` (only if drift) then `--reindex`.
- Verify clean: `ai/scripts/okf --check` → 0 errors, 0 broken links, 0 drift (provenance warnings
  for genuinely out-of-repo `source:` paths are expected and acceptable).

### Phase 4b — Cross-link pass (close the edgeless graph)
Cross-links only happen reliably if you *look* for them — a researcher seeing one source slice can't
spot most connections. After writing this campaign's notes:
1. Run **`ai/scripts/okf --suggest-links`** — it surfaces note pairs that share salient terms but have
   no edge yet (it drops corpus-generic terms; the output is a HINT, not an instruction).
2. For each candidate that is a *real* relationship, add a typed **`relations:`** entry — pick the verb
   (`supersedes`/`extends`/`refines`/`contradicts`/`relates`/`duplicates`). Reject coincidental
   term-overlap (the hint will produce some).
3. **Verified-safe rule (principle 2):** never edit a `verified`/human-authored note to add a back-link.
   Put the relation on the **`unverified` side** pointing at the verified note — the graph still connects
   — and add the suggested back-link to the **promotion queue** for the human to approve.
4. Re-run `ai/scripts/okf --check`: every relation must resolve (known verb + existing target).

### Phase 5 — Promotion handoff
- `ai/scripts/okf --review` prints the **promotion queue** (all `status: unverified` notes with
  title + source). Hand this to the operator: they check each against its `source`/`**Verify:**`
  and flip to `status: verified`. **You never promote.**
- Report: candidates found, minted, enriched, skipped (+why), dropped-as-ungrounded, conflicts
  resolved, and any "belongs in a verified note → minted adjacent, needs human merge" items.

## Tooling reference (global; reached via the per-project `ai/scripts/okf` shim)
- `ai/scripts/okf` (dry-run) · `--check` (strict) · `--apply` · `--reindex` · `--move SRC DST`
  (move + rewrite links) · `--touch` · `--review` (promotion queue) · `--render` (graph) · `--version`.
- Engine + viewer live once in the `init-ai-workspace` skill dir; projects carry only the shim + data.

## Anti-patterns (the ways this fails)
- Minting a concept whose claims you didn't grep-verify against the cited source ("cite or drop").
- Writing `status: verified` on a machine-derived note (only the human promotes).
- Editing/overwriting a `verified` or human-authored note to "enrich" it (mint adjacent instead).
- Capturing live numbers, secrets, or anything re-derivable from code/git as "timeless".
- Skipping the both-stores dedup and re-minting facts the global/personal memory already holds.
- Boiling the ocean — one unbounded run over a whole codebase instead of capped campaigns.
- Combining two notes' contents (that's a deliberate dedup at capture time, never an automatic step).
- Asking the operator to run the okf commands — the skill drives them; the operator only promotes.
