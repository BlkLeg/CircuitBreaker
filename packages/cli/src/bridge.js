import { spawn as nodeSpawn } from 'node:child_process';
import { constants } from 'node:os';

// Set on every forwarded child. The npm launcher refuses to run with it set, which
// breaks a cb → circuitbreaker → cb loop at the first repeat.
export const FORWARD_MARKER = 'CIRCUITBREAKER_FORWARDED';

// Signals a supervisor or `kill` sends to the launcher alone, so they are passed on.
// SIGINT is not in this list: a terminal's Ctrl-C already reaches the whole
// foreground process group, child included, and killing the child again from here
// would cut short its own cleanup (resources --watch restores the cursor, logs -f
// stops journalctl).
const RELAYED = ['SIGTERM', 'SIGHUP'];

export function forwardToNative({ cliPath, args, env = process.env, spawnImpl = nodeSpawn, proc = process }) {
  return new Promise((resolve, reject) => {
    const child = spawnImpl(cliPath, args, {
      stdio: 'inherit',
      shell: false,
      env: { ...env, [FORWARD_MARKER]: '1' },
    });
    const ignore = () => {};
    const relay = (signal) => child.kill(signal);
    proc.on('SIGINT', ignore);
    for (const signal of RELAYED) proc.on(signal, relay);
    const detach = () => {
      proc.off('SIGINT', ignore);
      for (const signal of RELAYED) proc.off(signal, relay);
    };
    child.once('error', (error) => {
      detach();
      reject(error);
    });
    child.once('close', (code, signal) => {
      detach();
      resolve(code ?? 128 + (constants.signals[signal] ?? 0));
    });
  });
}
