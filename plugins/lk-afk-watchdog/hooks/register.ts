import type { Register, Timer } from 'claude-code'

// lk-afk-watchdog: when the agent has answered and the person has not replied for
// `idleMinutes`, run the knowledge-system close-out unattended, once, so the session is
// captured (RESUME, session note, memory notes) while they are away.
//
// Arm on every main-loop turn end. Disarm on any prompt a person sent (composer, bridge,
// SDK: anything but a plugin's own) and at session end. Fire at most once per idle stretch:
// the close-out's own turn end must not arm it again, or it would close out forever.
// A `-p` run has nobody to wait for, so it never arms there.

const NAME = 'lk-afk-watchdog'
const COMMAND = 'lk-end-session'
const ARGS = '--headless'
const DEFAULT_MINUTES = 55

export const register: Register = (on, options) => {
  const raw = Number(options.idleMinutes ?? DEFAULT_MINUTES)
  const minutes = Number.isFinite(raw) && raw > 0 ? raw : DEFAULT_MINUTES
  const idleMs = Math.round(minutes * 60_000)

  let timer: Timer | null = null
  let isInteractive = true
  let hasFired = false

  const disarm = () => {
    if (timer !== null) {
      timer.cancel()
      timer = null
    }
  }

  on('session.start', ($, e, next) => {
    isInteractive = e.isInteractive
    hasFired = false
    disarm()
    return next(e)
  })

  on('prompt.submit', ($, e, next) => {
    if (e.origin.kind !== 'plugin') {
      // A person is here (or something speaking for them). Reset the stretch.
      disarm()
      hasFired = false
    }
    return next(e)
  }).catch(($, e, next) => next(e)) // an observer: never stand between the person and their prompt

  on('turn.complete', ($, e, next) => {
    if (e.agentId === undefined && isInteractive && !hasFired) {
      disarm()
      timer = $.clock.after(idleMs, () => {
        timer = null
        hasFired = true
        $.ui.log(`${NAME}: no reply for ${minutes} min, running /${COMMAND} ${ARGS}`)
        void $.command.run({ command: COMMAND, args: ARGS }).catch((error: unknown) => {
          $.ui.log(`${NAME}: /${COMMAND} did not run: ${String(error)}`)
        })
      })
    }
    return next(e)
  })

  on('session.end', ($, e, next) => {
    disarm()
    return next(e)
  })
}
