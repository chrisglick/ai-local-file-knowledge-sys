<!-- Copied to ai/contracts/_TEMPLATE-open-question.md by /init-ai-workspace, only if the
     govern-work skill is installed. This is a REFERENCE for the shape `gov --open` writes into
     ai/memory/ automatically -- you normally never hand-write one of these. It exists so the
     shape is visible without reading govern.py's source, and as a fallback if you need to file
     one by hand before the tooling is wired up somewhere.

     Normal path: `gov --open "<question>"` writes this file for you, correctly named and
     frontmattered, into ai/memory/. Close it later with:
       gov --rule ai/memory/open-question_<slug>.md --verbatim "<the human's own words, quoted>"
     which supersedes it with a `type: decision` note carrying the ruling verbatim, dated --
     never a paraphrase. An agent will argue with a paraphrase; it won't argue with a quote. -->

---
type: open-question
title: <the fork, as a short question>
description: <one line -- what's actually undecided, not what you think the answer is>
timestamp: YYYY-MM-DDTHH:MM:SSZ
created: YYYY-MM-DD
source: ai/scripts/gov
status: unverified
---

<The question, stated plainly, plus enough context that whoever answers it doesn't have to go
dig for the tradeoff. If this open question was raised BECAUSE of an existing decision note that
new evidence seems to contradict, name that note's id here -- R12: challenge a decision in the
ledger, never by silently ignoring it or re-arguing it in a diff.>

**Why this isn't self-evident:** <the tradeoff, or the two options, in one or two lines>
**Cites:** <optional -- the decision note id this challenges or relates to, if any>
