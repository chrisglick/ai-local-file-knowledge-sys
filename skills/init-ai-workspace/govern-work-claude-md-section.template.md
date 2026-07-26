<!-- govern-work -->
## Verify

<!-- FILL IN before minting any contract. Until this section says something real, `gov mint` and
     `gov --lint-spec` both refuse, on purpose: without a verify command, `gov land` can certify
     "the ledger is complete and the enforcement instruments are untouched" but it can NEVER
     certify "the work is correct" -- those are different claims, and only a real check closes
     the second one. For a codebase, that usually means tests; for a docs/research project with
     no test suite, set `govern_verify_trivially_true = true` in ai/okf.conf instead of leaving
     this placeholder (see that file's comment for what that trades away). -->

Run this from the repo root, exactly:

```
<TODO: the ONE blessed command -- e.g. `python -m pytest -q`, `npm test`, `make check`>
```

Expected: <TODO: the exact text the command prints when it passes>

<!-- The `Expected:` line above is a convention `gov verify` parses live from this file -- it
     never copies the expected text anywhere else, so there is only ever one copy to keep in
     sync. If a run is allowed to vary slightly (a timestamp, a count), name the tolerance in a
     trailing comment: `Expected: 12 passed <!-- band: total may vary by ±2 -->`. If you leave no
     `Expected:` line at all, `gov verify` still runs the command and checks its exit code, but
     without the stronger "and it actually printed what I expect" gate -- fine for a quick
     project, worth adding once the command's output is stable. -->
<!-- /govern-work -->
