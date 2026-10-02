import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runUninstall } from '../src/uninstall.js';

function host(reply = false) {
  const calls = []; let err = ''; let confirmations = 0;
  return { calls, deps: { out() {}, err(s) { err += s; }, confirm: async (phrase) => { confirmations++; assert.equal(phrase, 'DELETE'); return reply; } }, forward: async (...args) => { calls.push(args); return 17; }, error: () => err, confirmations: () => confirmations };
}

test('default uninstall forwards keep-data and preserves native exit status', async () => {
  const h = host();
  assert.equal(await runUninstall([], h.deps, h.forward), 17);
  assert.deepEqual(h.calls[0].slice(0, 2), ['uninstall', ['--keep-data']]);
  assert.equal(h.confirmations(), 0);
});

test('purge cancels before forwarding; exact DELETE or explicit --yes authorizes native purge', async () => {
  for (const [args, reply, code] of [[['--purge'], false, 2], [['--purge'], true, 17], [['--purge', '--yes'], false, 17]]) {
    const h = host(reply);
    assert.equal(await runUninstall(args, h.deps, h.forward), code);
    assert.equal(h.calls.length, code === 2 ? 0 : 1);
    if (code === 17) assert.deepEqual(h.calls[0].slice(0, 2), ['uninstall', ['--purge']]);
  }
});

test('conflicting flags, unknown flags and --plan are refused before removal', async () => {
  for (const args of [['--purge', '--keep-data'], ['--plan'], ['--unknown'], ['--yes', '; touch pwned']]) {
    const h = host();
    assert.equal(await runUninstall(args, h.deps, h.forward), 2);
    assert.equal(h.calls.length, 0);
  }
});
