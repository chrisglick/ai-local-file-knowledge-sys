# Phase 2.6 — Scaffold `govern-work` (loaded only when that skill is installed)

Loaded by `init-ai-workspace` SKILL.md only when the detection probe finds `govern.py`.
Scaffold it exactly like everything else in this skill — idempotent, marker-gated, create-only,
never overwrite existing content.

1. **The shim.** Copy `govern-work`'s own `gov.shim.sh` to `ai/scripts/gov` (create only if
   absent) and `chmod +x` it — identical mechanism to the `okf.shim.sh` → `ai/scripts/okf` copy
   in Phase 2. It resolves the global engine at `~/.claude/skills/govern-work/` (override with
   `GOV_SKILL_DIR`), same probe-and-fail-127 convention as the `okf` shim.

2. **Spec + note templates.** Create `ai/contracts/` if absent. Copy this skill's
   `_TEMPLATE-contract.template.md` to `ai/contracts/_TEMPLATE-contract.md` and
   `_TEMPLATE-open-question.template.md` to `ai/contracts/_TEMPLATE-open-question.md` — both
   create-only. These are copy-and-edit starting points for a human or agent minting a contract
   or (rarely) hand-filing an open question; the templates' own header comments explain the guard
   rules they exist to satisfy on the first try.

3. **Config.** `ai/okf.conf` already gets the full `govern-work settings` block (see this skill's
   `okf.conf.template`) whenever it's created fresh in Phase 2. For a project that already had an
   `ai/okf.conf` before this phase ran (upgrade case): check whether it already contains the
   marker text `govern-work settings` —
   ```bash
   grep -q "govern-work settings" ai/okf.conf 2>/dev/null && echo "already has the block" || echo "append it"
   ```
   If missing, *append* the same commented-out block from `okf.conf.template` (the section that
   starts `# govern-work settings` through its closing `# ---`) to the end of the existing
   `ai/okf.conf` — never touch anything already in that file.

4. **`.gitignore`.** Add `ai/contracts/*.json` (create-only append, if not already present) — this
   is where contract bookkeeping (worktree paths, timestamps) lives; it's operational state, not
   knowledge, and keeping it out of git from the start means the very first `gov mint` in this
   project never has to make its own bookkeeping commit just to keep the tree clean for `gov land`.

5. **`CLAUDE.md`.** Same append convention as Phase 3b, but a **separate marker**,
   `<!-- govern-work -->`, so this section and the `<!-- knowledge-system -->` section never
   collide or get confused for one another:
   - **No `<!-- govern-work -->` marker yet:** append this skill's
     `govern-work-claude-md-section.template.md` to root `CLAUDE.md` (create the file first if
     root `CLAUDE.md` doesn't exist yet — but in that case Phase 3b will already be creating it in
     the same run; append this section into the same file, after Phase 3b's content).
   - **Marker already present:** skip (idempotent).

   That template ships a `## Verify` section with a **deliberate placeholder** — `gov --lint-spec`
   and `gov mint` both refuse while it stands (they treat `TODO`/`<...>`-shaped text as
   unfilled), which is the intended behavior, not a bug: it forces a human to state the project's
   real verify command before any contract can be minted against it, and the refusal message says
   exactly what to fill in. It also carries the `Expected: <text>` line convention `gov verify`
   parses live from `CLAUDE.md` — filling that in (not just the command) gets the stronger "and it
   actually printed the right thing" gate, not just an exit-code check.

6. **The R15 verify-gap teaching block — print this ONCE, this run, only if needed.** After step 3
   above, check whether `ai/okf.conf` actually has a live (non-comment, non-empty)
   `govern_verify_command = ...` line. If it does not, print this block **once**, plainly, and
   move on — never repeat it on a later run. The trigger is the absence of the configured key,
   never "no tests exist" (a docs or research project legitimately has none):

   > **No verify command is configured yet.** Without one, `gov land` can certify "the ledger is
   > complete and the enforcement instruments are untouched" — but it can **never** certify "the
   > work is correct." Those are different claims, and only a real check closes the second one.
   > Setting `govern_verify_command` in `ai/okf.conf` is the single highest-leverage addition you
   > can make to this setup; for a codebase, that usually means your test command. If this project
   > genuinely has no automated check (a pure docs/research repo), set
   > `govern_verify_trivially_true = true` instead of leaving this blank — see the comment above
   > that key in `ai/okf.conf` for what that trades away.

## Verify checklist (used by SKILL.md Phase 5 when this phase ran)
- `ai/scripts/gov` exists and is executable.
- `ai/contracts/_TEMPLATE-contract.md` and `ai/contracts/_TEMPLATE-open-question.md` exist.
- `ai/okf.conf` contains the `govern-work settings` block.
- `CLAUDE.md` contains exactly one `<!-- govern-work -->` block.
- `.gitignore` contains `ai/contracts/*.json`.
- If no `govern_verify_command` is set: the R15 teaching block was shown exactly once this run.
