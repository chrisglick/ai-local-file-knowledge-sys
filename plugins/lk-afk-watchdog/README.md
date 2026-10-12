# lk-afk-watchdog

A Claude Code plugin (a hooks module) for the lk knowledge system. When the agent has answered
and the person has not replied for `idleMinutes` (55 by default), it runs
`/lk-end-session --headless` once, in the same session, so the session is captured (RESUME,
session note, memory notes, questions written down for the person) while they are away.

## Install

From a terminal session of Claude Code:

```
/plugin install lk-afk-watchdog --marketplace chrisglick/ai-local-file-knowledge-sys
```

Answer `y` to add the marketplace, pick the user scope, set the idle minutes if you want a
different window. It needs the `lk-end-session` skill installed (`~/.claude/skills/lk-end-session`).

From a local clone instead: `claude plugin marketplace add <clone folder>` then
`claude plugin install lk-afk-watchdog@lk`. A plugin installed from a folder marketplace is read
from that folder, so a `git pull` plus `/reload-plugins` is the upgrade.

## What it does, exactly

| Event | Action |
|---|---|
| `session.start` | remembers whether a person is at the prompt (`-p` runs never arm) |
| `turn.complete` (main loop) | arms a timer for `idleMinutes`, unless it already fired this idle stretch |
| `prompt.submit` from anything but a plugin | disarms, and the next answer may arm again |
| timer fires | one dim transcript line, then `$.command.run({ command: 'lk-end-session', args: '--headless' })` |
| `session.end` | disarms |

It fires at most once per idle stretch: the close-out's own turn end does not re-arm it, so a
session left overnight gets one close-out, not one every 55 minutes. Subagent turns never arm it.

What the headless close-out does and does not do is the `## Headless mode` section of
`lk-end-session/SKILL.md`: no questions asked, questions written into the session note and
RESUME instead, configured defaults used, nothing committed.

## Config

`idleMinutes` (number, default 55) in `/config`, or in `settings.json` under
`pluginConfigs["lk-afk-watchdog"].options`.

## Tests

`claude plugin test plugins/lk-afk-watchdog` (7 tests on a mocked clock).
