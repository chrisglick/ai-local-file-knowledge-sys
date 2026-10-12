import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

const MINUTE = 60_000
const START = { cwd: 'C:/project', surface: 'terminal', isInteractive: true } as const
const TURN = { answer: 'done', durationMs: 10, isAborted: false, turnId: 't1', reason: 'answer' } as const

// The engine beneath the plugin: a test answers every event it raises.
function recordRuns(on: On) {
  const runs: Array<{ command: string; args: string }> = []
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  on('prompt.submit', (_$, e) => ({ text: e.text }))
  on('session.end', (_$, e) => ({ sessionId: e.sessionId }))
  on('command.run', (_$, e) => {
    runs.push({ command: e.command, args: e.args })
    return { text: 'ok' }
  })
  return runs
}

test('runs /lk-end-session --headless once the person has been silent 55 minutes', async ($, on) => {
  const clock = mock.clock(on)
  const runs = recordRuns(on)
  await $.session.start(START)
  await $.turn.complete(TURN)
  await clock.advance(54 * MINUTE)
  expect(runs).toEqual([])
  await clock.advance(2 * MINUTE)
  expect(runs).toEqual([{ command: 'lk-end-session', args: '--headless' }])
})

test('a prompt from the person disarms it, and the next answer arms it again', async ($, on) => {
  const clock = mock.clock(on)
  const runs = recordRuns(on)
  await $.session.start(START)
  await $.turn.complete(TURN)
  await clock.advance(30 * MINUTE)
  await $.prompt.submit({ text: 'still here', origin: { kind: 'composer' }, wait: false })
  await clock.advance(40 * MINUTE)
  expect(runs).toEqual([])
  await $.turn.complete({ ...TURN, turnId: 't2' })
  await clock.advance(56 * MINUTE)
  expect(runs.length).toBe(1)
})

test('fires once per idle stretch: the close-out turn does not re-arm it', async ($, on) => {
  const clock = mock.clock(on)
  const runs = recordRuns(on)
  await $.session.start(START)
  await $.turn.complete(TURN)
  await clock.advance(56 * MINUTE)
  expect(runs.length).toBe(1)
  await $.turn.complete({ ...TURN, turnId: 'closeout' })
  await clock.advance(120 * MINUTE)
  expect(runs.length).toBe(1)
})

test('a subagent turn never arms it', async ($, on) => {
  const clock = mock.clock(on)
  const runs = recordRuns(on)
  await $.session.start(START)
  await $.turn.complete({ ...TURN, agentId: 'a1' })
  await clock.advance(120 * MINUTE)
  expect(runs).toEqual([])
})

test('a non-interactive session (-p) never arms it', async ($, on) => {
  const clock = mock.clock(on)
  const runs = recordRuns(on)
  await $.session.start({ ...START, surface: null, isInteractive: false })
  await $.turn.complete(TURN)
  await clock.advance(120 * MINUTE)
  expect(runs).toEqual([])
})

test('session end disarms it', async ($, on) => {
  const clock = mock.clock(on)
  const runs = recordRuns(on)
  await $.session.start(START)
  await $.turn.complete(TURN)
  await $.session.end({ reason: 'exit', sessionId: 's1', resume: { sessionId: 's1' } })
  await clock.advance(120 * MINUTE)
  expect(runs).toEqual([])
})

test('idleMinutes is configurable', { options: { idleMinutes: 2 } }, async ($, on) => {
  const clock = mock.clock(on)
  const runs = recordRuns(on)
  await $.session.start(START)
  await $.turn.complete(TURN)
  await clock.advance(1 * MINUTE)
  expect(runs).toEqual([])
  await clock.advance(1.5 * MINUTE)
  expect(runs.length).toBe(1)
})
