import { createEventWriter } from './events.js';

// Static, append-only phase lines. No terminal ownership, cursor movement or ANSI.
// Machine streams and forwarded management commands never use this renderer.
export function createPhaseRenderer({ write, now = Date.now, env = {} }) {
  const ascii = env.TERM === 'dumb' || env.CB_ASCII === '1' || env.LC_ALL === 'C';
  const good = ascii ? 'OK' : '✓';
  const bad = ascii ? 'FAIL' : '✗';
  const render = (event) => {
    if (event.type !== 'phase') return;
    if (event.status === 'started') return;
    const mark = event.status === 'failed' ? bad : event.status === 'skipped' ? '-' : good;
    const time = event.duration_ms === undefined ? '' : ` (${(event.duration_ms / 1000).toFixed(1)}s)`;
    write(`${mark} ${event.phase}${time}\n`);
  };
  const events = createEventWriter({ write: (line) => render(JSON.parse(line)), now });
  return {
    ...events,
    machine: false,
    // Native phase envelopes are validated by the descriptor decoder first.
    relay: render,
    diagnostic(message) { write(`${message}\n`); },
  };
}
