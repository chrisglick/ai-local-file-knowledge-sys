# Phase 1 — Migrate `.ai/` → `ai/` (approval-gated)

Loaded by `init-ai-workspace` SKILL.md only when `.ai/` exists. Show the plan and get a yes
before running it (governing principle 3); use `git mv` so renames keep blame/history.

1. **Collision safety check FIRST — never rewrite a `.ai` domain URL** (e.g. `mem0.ai/`):
   `grep -rn '[A-Za-z0-9]\.ai/' --include='*.md' --include='*.ts' --include='*.mjs' --include='*.json' --include='*.sh' --include='*.html' --exclude-dir=node_modules --exclude-dir=.git .`
   If any hits are real domains, exclude those files/lines from the sed below (do them by hand).
   Running the rename sed before this check is how domain URLs get corrupted.
2. **Check for untracked files** under `.ai/`: `git status --porcelain .ai/ | grep '^??'`.
   `git mv` only moves tracked files — move any untracked stragglers with plain `mv` afterward.
3. **Rename (git repo):** `git mv .ai ai` — then move untracked leftovers: `[ -d .ai ] && mv .ai/* ai/ 2>/dev/null; [ -d .ai ] && rmdir .ai`.
   **Non-git:** plain `mv .ai ai`.
4. **Update forward-slash references** across text files (safe after the collision check):
   `grep -rlZ --include='*.md' --include='*.ts' --include='*.mjs' --include='*.json' --include='*.sh' --include='*.html' --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=dist '\.ai/' . | xargs -0 -r sed -i 's#\.ai/#ai/#g'`
5. **Update Windows backslash references** (`...\.ai\...`) — sed backslash escaping is unreliable,
   so never blanket-sed these; find them with `grep -rn '\.ai\\' --include='*.md' .` and fix each
   with an exact Edit (`\.ai\` → `\ai\`). Don't forget any external memory/notes index that names
   the path.
6. **Verify zero stragglers** (the one canonical placement of this check):
   `git grep -n '\.ai[/\\]' -- ':!node_modules'` must return nothing.

If the working tree has unrelated changes, flag that the rename commit will be tangled with them —
offer to commit the migration separately.
